import re
import html
import logging
import requests
from bs4 import BeautifulSoup
import xml.etree.ElementTree as ET

arr = []
invalidArr = []
BASE_URL = "https://api.congress.gov/v3/bill"

# now uses api to get it instead of webscraping
def getTextandSummary(url, is_senate):
    with open("utils/govkey.txt") as f:
        api_key = f.read().strip()

    congress = 119

    bill_number = url.rstrip("/").split("/")[-1]
    print("Bill number:", bill_number)

    bill_type = "s" if is_senate else "hr"

    headers = {"X-API-Key": api_key, "Accept": "application/xml"}
    base_path = f"{BASE_URL}/{congress}/{bill_type}/{bill_number}"

    # === Get Summary XML ===
    summary_url = f"{base_path}/summaries"
    summary_resp = requests.get(summary_url, headers=headers)
    summary_root = ET.fromstring(summary_resp.content)

    # Get the last <summary><cdata><text> element
    summary_text = None
    summaries = summary_root.findall(".//summary")
    if summaries:
        latest_summary = summaries[-1]  # most recent version
        cdata = latest_summary.find(".//text")
        if cdata is not None and cdata.text:
            summary_text = html.unescape(cdata.text.strip())

    # === Get Text XML ===
    text_url = f"{base_path}/text"
    text_resp = requests.get(text_url, headers=headers)
    text_root = ET.fromstring(text_resp.content)

    # Get first <textVersions><item><formats><item><url> for HTML
    html_text_url = None
    first_text_item = text_root.find(".//textVersions/item")
    if first_text_item is not None:
        formats = first_text_item.findall(".//formats/item")
        for f in formats:
            type_tag = f.find("type")
            url_tag = f.find("url")
            if type_tag is not None and "Formatted Text" in type_tag.text:
                html_text_url = url_tag.text.strip()
                break

    bill_text = None
    if html_text_url:
        try:
            bill_html = requests.get(html_text_url)
            bill_html.raise_for_status()
            soup = BeautifulSoup(bill_html.content, "html.parser")
            # Remove script, nav, header, footer tags
            for tag in soup(["script", "style", "nav", "header", "footer"]):
                tag.decompose()
            bill_text = soup.get_text(separator="\n", strip=True)
        except Exception as e:
            print(f"Failed to fetch or parse bill text HTML: {e}")

    return bill_text, summary_text

def get_primary_sponsor(is_senate, congress_num, bill_number):
    """
    Returns the full sponsor name string as it appears in Congress.gov API (e.g., 'Sen. Sheehy, Tim [R-MT]')
    """
    with open("utils/govkey.txt") as f:
        api_key = f.read().strip()
    
    # title = "Sen. " if is_senate else "Rep. "
    # label = "S. " if is_senate else "H.R. "
    url_label = "s" if is_senate else "hr"

    url = f"https://api.congress.gov/v3/bill/{congress_num}/{url_label}/{bill_number}" 

    parameters = {
    "api_key": api_key,
    "limit": 250
    }
    
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

    sponsor_str += f"{sponsor_name}, {sponsor[0]['party']}-{sponsor[0]['state']},"

    return sponsor_str, last_name


def extract_sponsor_phrase(html_string):
    decoded = html.unescape(html_string)

    # Extract <pre> ... </pre>
    pre_match = re.search(r"<pre>(.*?)</pre>", decoded, re.DOTALL)
    if not pre_match:
        return None
    pre_text = pre_match.group(1)

    # Match up to the word 'introduced' — no whitespace requirement
    match = re.search(
        r"((?:Mr\.|Mrs\.|Ms\.|Dr\.)\s+.*?)(?=introduced)",
        pre_text,
        re.DOTALL
    )

    if match:
        return ' '.join(match.group(1).split())  # normalize whitespace
    return None

def get_most_recent_bill_number(is_senate, congress=119):
    """
    Returns the highest-introduced bill number for the given chamber and congress session.
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

        max_number = -1
        for bill in bills:
            number_str = bill.get("number")
            if number_str and number_str.isdigit():
                number_int = int(number_str)
                if number_int > max_number:
                    max_number = number_int

        logging.info(f"Most recent bill number found on bill website: {max_number}")

        return max_number

    except requests.exceptions.HTTPError as e:
        logging.error(f"HTTP error: {e}")
        return -1
    except Exception as e:
        logging.error(f"Error: {e}")
        return -1
