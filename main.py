#!/usr/bin/python3

# adding all requirements
import sys
import getopt
import logging
from datetime import datetime
from email_utils import send_summary_email
from openai_api import callApiWithText, OpenAI
from url_processing import getTextandSummary, extract_sponsor_phrase
from db_utils import get_db_connection, populateDB, populateCsv, insert_story, load_pending_urls_from_db, mark_url_processed, link_story_to_url, add_note_to_url
from shared_utils import getKey

# logfile setup
logfile = f"logs/scrape_log.{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.log"
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s %(name)-12s %(levelname)-8s %(message)s",
    datefmt="%m-%d %H:%M:%S",
    filename=logfile,
    filemode="w"
)
console = logging.StreamHandler()
console.setLevel(logging.INFO)
formatter = logging.Formatter("%(name)-12s: %(levelname)-8s %(message)s")
console.setFormatter(formatter)
logging.getLogger("").addHandler(console)

# main runner
def main(argv):
    # initializing starting variables
    start_time = datetime.now()

    # tallies for summary email
    processed, skipped, total_urls, passed = 0, 0, 0, 0
    test_run = False
    is_senate = None
    a_id = 0
    stopped = False
    test_range = None
    populate_first = False

    try:
        # -t takes two arguments, so specify "t:" in the option string
        opts, args = getopt.getopt(argv, "shpt:")
    except getopt.GetoptError:
        print("Usage: [-p] -s|-h | -t <start> <end>")
        sys.exit(1)

    # parse options
    for opt, arg in opts:
        if opt == "-s":
            if is_senate is False:
                print("Error: cannot specify both -s and -h")
                sys.exit(1)
            is_senate = True
            a_id = 56
        elif opt == "-h":
            if is_senate is True:
                print("Error: cannot specify both -s and -h")
                sys.exit(1)
            is_senate = False
            a_id = 57
        elif opt == "-p":
            populate_first = True
        elif opt == "-t":
            # -t mode: special case
            if is_senate is not None or populate_first:
                print("Error: -t cannot be used with -p, -s, or -h")
                sys.exit(1)
            try:
                # arg is the first number, args should still contain the second
                start = int(arg)
                if not args:
                    raise ValueError("Missing second integer for -t")
                end = int(args[0])
                test_range = (start, end)
                test_run = True
            except (ValueError, IndexError):
                print("Error: -t must be followed by two integer arguments (e.g., -t 100 120)")
                sys.exit(1)

            # run -t and exit early
            populateCsv(test_range)
            return

    # ensure s or h provided (unless in test mode, already returned)
    if is_senate is None:
        print("Error: Must specify -s or -h (unless using -t)")
        sys.exit(1)

    # populate DB if requested
    if populate_first:
        populateDB()

    # gets up to 2000 new bill urls per day (checked in smaller batches as to not rack up run time)
    url_rows = load_pending_urls_from_db(is_senate)  

    # setting up openai gpt client
    client = OpenAI(api_key=getKey())
    seen = set()

    # goes through every url and proccesses it accordingly
    for url_id, url in url_rows:
        canonical = url.strip().rstrip('/')
        if canonical in seen:
            continue
        seen.add(canonical)
        total_urls += 1

        if 'congress.gov' in url and not url.endswith('/text'):
            url += '/text'

        # grabbing the text and the text summary from the bill intro
        content, summary, summary_date = getTextandSummary(url, is_senate)

        # if there isnt both summary and text availble, pass it and try again tommorow
        if not content or not summary or not summary_date:
            add_note_to_url(url_id, "No text and/or summary found yet")
            passed += 1
            continue
        
        # if text and summary available, create bill summary press release story
        bill_sponsor_blob = extract_sponsor_phrase(content)

        filename_preview, _, _ = callApiWithText(
            text=content,
            summary=summary,
            summary_date=summary_date,
            client=client,
            url=url,
            is_senate=is_senate,
            filename_only=True  
        )

        # if filename couldnt be generated, pass and reevaluate tommorow
        if not filename_preview:
            logging.warning(f"Filename preview failed for {url}")
            add_note_to_url(url_id, "Filename preview failed")
            passed += 1
            continue
        
        # starting db connection and checking for duplicate entries
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM story WHERE filename = %s", (filename_preview,))
        if cursor.fetchone()[0] > 0:
            logging.info(f"Skipping duplicate before GPT call: {filename_preview}")
            add_note_to_url(url_id, "Duplicate filename in story table")
            skipped += 1
            # marking it as processed so that it isnt processed again
            mark_url_processed(url_id)
            conn.close()
            continue
        conn.close()
        
        # getting all data to put into DB
        filename, headline, press_release = callApiWithText(
            text=content,
            summary=summary,
            summary_date=summary_date,
            client=client,
            url=url,
            is_senate=is_senate,
            filename_only=False  
        )

        # if a stop marker is hit, set email summary values accordingly
        if filename == "STOP":
            stopped = True
            break
        
        if filename == "NA" or not headline or not press_release:
            logging.warning(f"Skipped due to text not being available through api {url}")
            add_note_to_url(url_id, "text not available through api")
            passed += 1
            continue
        
        # if all data is valid, insert story into TNS DB
        if filename and headline and press_release:
            full_text = press_release + f"\n\n* * # * *\n\nPrimary source of information: {url}"
            s_id = insert_story(filename, headline, full_text, a_id, bill_sponsor_blob)
            if s_id:
                mark_url_processed(url_id)
                link_story_to_url(url_id, s_id)
                processed += 1
            else:
                add_note_to_url(url_id, "Story insert failed (possibly DB error)")
                passed += 1

    # generate summary email
    end_time = datetime.now()
    elapsed = str(end_time - start_time).split('.')[0]
    summary = f"""
Load Version 1.0.1 09/08/2025

Passed Parameters: {' -t' if test_run else ''}  {' -p' if populate_first else ''} {' -S' if is_senate else ' -H'}
Pull House and Senate: {'Senate' if is_senate else 'House'}

Docs Loaded: {processed}
URLS skipped due to duplication: {skipped}
URLS held for re-evaluation: {passed}
Total URLS looked at: {total_urls}

Stopped Due to Rate Limit: {stopped}

Start Time: {start_time.strftime('%Y-%m-%d %H:%M:%S')}
End Time: {end_time.strftime('%Y-%m-%d %H:%M:%S')}
Elapsed Time: {elapsed}
"""
    logging.info(summary)
    logging.shutdown()
    send_summary_email(summary, is_senate, logfile)

# runs the file
if __name__ == "__main__":
    main(sys.argv[1:])
