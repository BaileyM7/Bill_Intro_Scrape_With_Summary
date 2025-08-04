#!/usr/bin/python3
import sys
import getopt
import logging
from datetime import datetime
from db_utils import get_db_connection
from email_utils import send_summary_email
from db_utils import populateDB, populateCsv, insert_story
from openai_api import getKey, callApiWithText, OpenAI
from url_processing import getDynamicUrlText, load_pending_urls_from_db, mark_url_processed, extract_sponsor_phrase, link_story_to_url, add_note_to_url

# --- Logging Setup ---
logfile = f"scrape_log.{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.log"
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

# --- Main Processing ---
def main(argv):
    start_time = datetime.now()
    processed, skipped, total_urls, passed = 0, 0, 0, 0
    test_run = False
    is_senate = None
    a_id = 0
    stopped = False
    test_range = None
    populate_first = False

    # Handle optional -p flag
    if '-p' in argv:
        populate_first = True
        argv.remove('-p')

    # Handle -t number number
    if '-t' in argv:
        t_index = argv.index('-t')
        try:
            start = int(argv[t_index + 1])
            end = int(argv[t_index + 2])
            test_range = (start, end)
            test_run = True
            # Remove -t and its arguments
            argv = argv[:t_index] + argv[t_index + 3:]
        except (IndexError, ValueError):
            print("Error: -t must be followed by two integer arguments")
            sys.exit(1)

    try:
        opts, args = getopt.getopt(argv, "sh")
    except getopt.GetoptError:
        print("Usage: [-p] [-t start end] -s|-h")
        sys.exit(1)

    for opt, _ in opts:
        if opt == "-s":
            is_senate = True
            a_id = 56
        elif opt == "-h":
            is_senate = False
            a_id = 57

    if is_senate is None:
        print("Must specify -s or -h")
        sys.exit(1)

    # optional behaviors
    if populate_first:
        populateDB()

    if test_run:
        populateCsv(test_range)


    url_rows = load_pending_urls_from_db(is_senate)  

    client = OpenAI(api_key=getKey())
    seen = set()

    for url_id, url in url_rows:
        canonical = url.strip().rstrip('/')
        if canonical in seen:
            continue
        seen.add(canonical)
        total_urls += 1

        if 'congress.gov' in url and not url.endswith('/text'):
            url += '/text'

        content = getDynamicUrlText(url, is_senate)

        if not content:
            add_note_to_url(url_id, "No content extracted: broken link")
            passed += 1
            continue

        bill_sponsor_blob = extract_sponsor_phrase(content)

        filename_preview, _, _ = callApiWithText(
            text=content,
            client=client,
            url=url,
            is_senate=is_senate,
            filename_only=True  
        )

        if not filename_preview:
            logging.warning(f"Filename preview failed for {url}")
            add_note_to_url(url_id, "Filename preview failed")
            passed += 1
            continue
        
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
        
        filename, headline, press_release = callApiWithText(
            text=content,
            client=client,
            url=url,
            is_senate=is_senate, 
            filename_only=False
        )

        if filename == "STOP":
            stopped = True
            break
        
        if filename == "NA" or not headline or not press_release:
            logging.warning(f"Skipped due to text not being available through api {url}")
            add_note_to_url(url_id, "text not available through api")
            passed += 1
            continue

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

    end_time = datetime.now()
    elapsed = str(end_time - start_time).split('.')[0]
    summary = f"""
Load Version 1.0.0 08/4/2025

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
    
if __name__ == "__main__":
    main(sys.argv[1:])
