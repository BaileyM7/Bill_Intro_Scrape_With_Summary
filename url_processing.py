import re
import requests
import html
import logging

arr = []
invalidArr = []

# now uses api to get it instead of webscraping
def getDynamicUrlText(url, is_senate):
    """Fetch bill text using Congress.gov API and fallback to govinfo.gov."""
    with open("utils/govkey.txt") as f:
        api_key = f.read().strip()

    congress = 119

    match = re.search(r'/bill/(\d+)[a-z\-]*/(senate|house)-bill/(\d+)', url)
    if not match:
        # logging.info(f"Unable to parse bill info from URL: {url}")
        # add_invalid_url(url)
        return None

    _, bill_type_text, bill_number = match.groups()
    bill_type = "s" if is_senate else "hr"

    api_url = f"https://api.congress.gov/v3/bill/{congress}/{bill_type}/{bill_number}/text"
    # logging.info(api_url)
    headers = {"X-API-Key": api_key}

    try:
        response = requests.get(api_url, headers=headers)
        response.raise_for_status()  # raises HTTPError for 4xx or 5xx
    except requests.exceptions.RequestException as e:
        logging.info(f"[ERROR] Failed to fetch bill text for {url}: {e}")
        # add_invalid_url(url)
        return None

    if response.status_code == 200:
        data = response.json()
        versions = data.get("billText", {}).get("versions", [])
        for version in versions:
            for fmt in version.get("formats", []):
                if fmt["format"] == "html":
                    html_url = fmt["url"]
                    html_response = requests.get(html_url)
                    if html_response.status_code == 200:
                        text = html_response.text.replace("<html><body><pre>", "").strip()
                        return text
        #             else:
        #                 logging.info(f"Failed to fetch HTML content: {html_response.status_code}")
        # logging.info("HTML version not found in formats.")
    # else:
    #     logging.info(f"Congress API failed: {response.status_code}")

    # Fallback: govinfo.gov
    #logging.info("Trying govinfo.gov...")
    if is_senate:
        govinfo_url = f"https://www.govinfo.gov/content/pkg/BILLS-{congress}{bill_type}{bill_number}is/html/BILLS-{congress}{bill_type}{bill_number}is.htm"
    else:

        govinfo_url = f"https://www.govinfo.gov/content/pkg/BILLS-{congress}{bill_type}{bill_number}ih/html/BILLS-{congress}{bill_type}{bill_number}ih.htm"
        
    response = requests.get(govinfo_url)
    if response.status_code == 200:

        if "Page Not Found" in response.text or "Error occurred" in response.text:
            return None
        
        return response.text
    else:
        # logging.info("Bill text not yet published on govinfo.gov.")
        # add_invalid_url(url)
        return None

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
