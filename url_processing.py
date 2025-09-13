import re
import html
import logging
import requests
import xml.etree.ElementTree as ET

# this is used to access summary and text data for the bill intros
API_BASE = "https://api.congress.gov/v3/bill"

# HTML tag stripper using regex (makes the text cleaner when feeding it to gpt api)
def strip_tags(html_text):
    return re.sub(r"<[^>]+>", "", html_text).strip()

# gets the text field and the summary field from a given bill intro
def getTextandSummary(url, is_senate):
    # getting the congress.gov api key
    with open("utils/govkey.txt") as f:
        api_key = f.read().strip()

    congress = 119 # to be changed when a new congress starts
    parts = url.rstrip("/").split("/")
    bill_number = parts[-1]
    if bill_number == "text":  # handle trailing /text URLs
        bill_number = parts[-2]
    print("Bill number:", bill_number)

    # setting up headers and variables based off of whether it is a house or senate bill
    bill_type = "s" if is_senate else "hr"
    headers = {"X-API-Key": api_key}
    summary_text = None
    bill_text = None
    summary_date = None

    # getting the summary in two different ways (Because the congress.gov DB is inconcistant in its way of adding data)
    # The data will either be available via json or xml format, which isnt known at the time of scraping

    # setting up url and response variables
    summary_url = f"{API_BASE}/{congress}/{bill_type}/{bill_number}/summaries"
    summary_resp = requests.get(summary_url, headers=headers)

    # if json available, then take json
    if summary_resp.ok and summary_resp.headers.get("Content-Type", "").startswith("application/json"):
        if summary_resp.content.strip():
            try:
                data = summary_resp.json()
                summaries = data.get("summaries", [])
                if summaries:
                    summary_date = summaries[-1].get("actionDate") # this gets the date that the summary was produced
                    latest = summaries[-1]
                    raw_html = latest.get("text", "")
                    summary_text = html.unescape(strip_tags(raw_html))
            except Exception as e:
                print(f"Error parsing summary JSON for {bill_number}: {e}")
        else:
            print(f"Empty summary response for {bill_number}")
    # if xml available, then take json
    elif summary_resp.ok and summary_resp.headers.get("Content-Type", "").startswith("application/xml"):
        try:
            root = ET.fromstring(summary_resp.content)
            summaries = root.findall(".//summary")
            if summaries:
                latest = summaries[-1]
                summary_date = latest.find(".//actionDate") # gets the date that the summary was released
                text_elem = latest.find(".//text")
                if text_elem is not None and text_elem.text:
                    summary_text = html.unescape(text_elem.text.strip())
                    print("[XML SUMMARY] Parsed from fallback XML")
        except Exception as e:
            print(f"Error parsing summary XML for {bill_number}: {e}")
    else:
        print(f"Summary fetch failed for {bill_number}")

    # The same thing occurs for the bill intro text, sometimes it is in json or xml format

    # setting up bill intro get request and response variables
    text_url = f"{API_BASE}/{congress}/{bill_type}/{bill_number}/text"
    text_resp = requests.get(text_url, headers=headers)

    formatted_url = None

    # if json version of text is availble, use it
    if text_resp.ok and text_resp.headers.get("Content-Type", "").startswith("application/json"):
        if text_resp.content.strip():
            try:
                data = text_resp.json()
                versions = data.get("textVersions", [])
                if versions:
                    for fmt in versions[0].get("formats", []):
                        if fmt.get("type") == "Formatted Text":
                            formatted_url = fmt.get("url")
                            break
            except Exception as e:
                print(f"Error parsing text JSON for {bill_number}: {e}")
        else:
            print(f"Empty bill text response for {bill_number}")
    # if xml version of text is availble, use it
    elif text_resp.ok and text_resp.headers.get("Content-Type", "").startswith("application/xml"):
        try:
            root = ET.fromstring(text_resp.content)
            item = root.find(".//textVersions/item")
            if item is not None:
                formats = item.findall(".//formats/item")
                for fmt in formats:
                    type_elem = fmt.find("type")
                    url_elem = fmt.find("url")
                    if type_elem is not None and "Formatted Text" in type_elem.text:
                        formatted_url = url_elem.text.strip()
                        break
            print("[XML TEXT] Parsed from fallback XML")
        except Exception as e:
            print(f"Error parsing text XML for {bill_number}: {e}")
    else:
        print(f"Text metadata fetch failed for {bill_number}")

    if formatted_url:
        raw_html_resp = requests.get(formatted_url)

        if raw_html_resp.ok:
            bill_text = html.unescape(strip_tags(raw_html_resp.text))
        else:
            print(f"Formatted text HTML fetch failed: {raw_html_resp.status_code}")
    # print(bill_text, summary_text)
    # returning the raw bill text and raw summary text
    return bill_text, summary_text, summary_date

# gets the primary sponsor of the bill
def get_primary_sponsor(is_senate, congress_num, bill_number):
    with open("utils/govkey.txt") as f:
        api_key = f.read().strip()
    
    url_label = "s" if is_senate else "hr"

    url = f"https://api.congress.gov/v3/bill/{congress_num}/{url_label}/{bill_number}" 

    parameters = {
    "api_key": api_key,
    "limit": 250
    }
    
    # using two request to get to a DB that has very consistant spelling of Sen and Rep names
    try: 
        # first request
        response = requests.get(url, parameters)
        response.raise_for_status()
        sponsor = response.json()['bill']['sponsors']

        # second request
        name_url = sponsor[0]['url']
        directOrderID = requests.get(name_url, parameters)
        sponsor_name = directOrderID.json()['member']['directOrderName']
        last_name = directOrderID.json()['member']['lastName']

    # logging errors if they occur
    except requests.exceptions.HTTPError as e:
        status = response.status_code
        if status == 502:
            logging.info(f"502 Bad Gateway for URL: {url}")
            return "", ""
        elif status == 429:
            logging.info(f"429 Too Many Requests for URL: {url}")
            return "STOP", ""
        else:
            logging.info(f"HTTP error {status} for URL: {url}")
            return "", ""
    
    sponsor_str = ""

    if not sponsor:
        logging.info(f"No sponsors found for {url}")
        return "", ""

    # returning the formatted sponsor string
    sponsor_str += f"{sponsor_name}, {sponsor[0]['party']}-{sponsor[0]['state']},"

    return sponsor_str, last_name

# getting the list of all the people that worked on the bill
def extract_sponsor_phrase(html_string):
    decoded = html.unescape(html_string)

    # extracting <pre> ... </pre>
    pre_match = re.search(r"<pre>(.*?)</pre>", decoded, re.DOTALL)
    if not pre_match:
        return None
    pre_text = pre_match.group(1)

    # match up to the word 'introduced' — no whitespace requirement
    match = re.search(
        r"((?:Mr\.|Mrs\.|Ms\.|Dr\.)\s+.*?)(?=introduced)",
        pre_text,
        re.DOTALL
    )

    if match:
        return ' '.join(match.group(1).split())  # normalize whitespace
    return None

# geting the most recent bill number that is available on the congress website for the given session
def get_most_recent_bill_number(is_senate, congress=119):
    """
        gets congress.gov api key and calls a batch of 250 bills with latest action
        since the api has no way of calling for a bill by date introduced, 
        I just gather the ones with the latest action and take the bill with the largest number
    """
    try:
        with open("utils/govkey.txt") as f:
            api_key = f.read().strip()

        bill_type = "s" if is_senate else "hr"
        url = f"https://api.congress.gov/v3/bill/{congress}/{bill_type}"
        params = {
            "api_key": api_key,
            "limit": 250  # max allowed
        }

        response = requests.get(url, params=params)
        response.raise_for_status()
        bills = response.json().get("bills", [])

        # getting the largest bill number
        max_number = -1
        for bill in bills:
            number_str = bill.get("number")
            if number_str and number_str.isdigit():
                number_int = int(number_str)
                if number_int > max_number:
                    max_number = number_int

        logging.info(f"Most recent bill number found on bill website: {max_number}")

        return max_number

    # logging errors accordingly
    except requests.exceptions.HTTPError as e:
        logging.error(f"HTTP error: {e}")
        return -1
    except Exception as e:
        logging.error(f"Error: {e}")
        return -1
