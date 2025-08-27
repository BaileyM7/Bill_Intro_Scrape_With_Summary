import re
from datetime import datetime
from openai import OpenAI
from urllib.parse import urlparse
import platform
from cleanup_text import cleanup_text
from url_processing import get_primary_sponsor
import requests

global found_ids
found_ids = {}

# used for tagging purposes
state_ids = {
 'AL' :67,                          
 'AK' :68,                          
 'AZ' :69,                          
 'AR' :70,                          
 'CA' :71,                          
 'CO' :72,                          
 'CT' :73,                          
 'DE' :74,                          
 'DC' :75,                          
 'FL' :76,                          
 'GA' :77,                          
 'HI' :78,                          
 'ID' :79,                          
 'IL' :80,                          
 'IN' :81,                          
 'IA' :82,                          
 'KS' :83,                          
 'KY' :84,                          
 'LA' :85,                          
 'ME' :86,                          
 'MD' :87,                          
 'MA' :88,                          
 'MI' :89,                          
 'MN' :90,                          
 'MS' :91,                          
 'MO' :92,                          
 'MT' :93,                          
 'NE' :94,                          
 'NV' :95,                          
 'NH' :96,                          
 'NJ' :97,                          
 'NM' :98,                          
 'NY' :99,                          
 'NC' :100,                         
 'ND' :101,                         
 'OH' :102,                         
 'OK' :103,                         
 'OR' :104,                         
 'PA' :105,                         
 'RI' :106,                         
 'SC' :107,                         
 'SD' :108,                         
 'TN' :109,                         
 'TX' :110,                         
 'UT' :111,                         
 'VT' :112,                         
 'VA' :113,                         
 'WA' :114,                         
 'WV' :115,                         
 'WI' :116,                         
 'WY' :117,                         
}

# Cleans text for readability and ASCII compliance.
def clean_text(text):
    text = cleanup_text(text)  # Replace non-ASCII chars
    text = re.sub(r'\*\*', '', text)  
    text = re.sub(r'""', '"', text)
    text = re.sub(r'###', '', text)
    text = text.replace("[NEWLINE SEPARATOR]", "")
    text = text.strip().replace('\"', "").replace('Headline:', "").replace('headline:', "")
    return text

def format_date_into_words(date_str):
    """
    Converts a date string in 'YYYY-MM-DD' format to 'Month Day, Year' format.
    Works on both Linux and Windows.
    
    Example:
        format_date("2025-03-12") -> "March 12, 2025"
    """
    try:
        date_obj = datetime.strptime(date_str, "%Y-%m-%d")
        formatted = date_obj.strftime("%B %d, %Y")
        return formatted.replace(" 0", " ")  # Ensures "March 01" -> "March 1"
    except ValueError:
        return "Invalid date format"

def get_date_from_text(text, is_file):
    """
    Extract the introduction date after:
    'IN THE HOUSE OF REPRESENTATIVES' or 'IN THE SENATE OF THE UNITED STATES',
    allowing for extra text like "(legislative day, March 10)" between the date.
    
    If is_file is True, returns the date as MMDDYY (e.g., "031125").
    If is_file is False, returns the date as MM/DD/YYYY (e.g., "03/11/2025").
    """
    pattern = (
        r"IN THE (?:HOUSE OF REPRESENTATIVES|SENATE OF THE UNITED STATES)[^\n]*\n"
        r"\s*([A-Z][a-z]+ \d{1,2})(?: \([^)]+\))?, (\d{4})"
    )
    match = re.search(pattern, text, flags=re.IGNORECASE)
    if match:
        try:
            full_date = f"{match.group(1)}, {match.group(2)}"  # e.g., "March 11, 2025"
            dt = datetime.strptime(full_date, "%B %d, %Y")
            if is_file:
                # Return as YYMMDD with leading zeros
                return dt.strftime("%y%m%d")
            else:
                # Return as MM/DD/YYYY
                return f"{dt.month}/{dt.day}/{dt.year}"
        except ValueError:
            return None
    return None

def extract_found_ids(press_release):
    global found_ids
    found_ids = {}

    # Match either [R-UT], [D-NY-14], or R-UT, D-TX (non-bracketed)
    pattern = re.compile(r'\b[DRI]-([A-Z]{2})(?:-\d{1,2})?\b')


    matches = pattern.findall(cleanup_text(press_release))

    for abbr in set(matches):
        if abbr in state_ids:
            found_ids[abbr] = state_ids[abbr]
    # print(found_ids)
    # print(len(found_ids))
    return found_ids

def callApiWithText(text, summary, summary_date, client, url, is_senate, filename_only=False):
    # gathering info to then create the output for filename, headline, and body
    today = datetime.today()
    text = re.sub(r'https://www\.congress\.gov[^\s]*', '', text)
    month = today.strftime('%B') 
    short_month = today.strftime('%b')
    formatted_month = month if len(month) <= 5 else short_month + "."
    day_format = '%-d' if platform.system() != 'Windows' else '%#d'
    today_date = f"{formatted_month} {today.strftime(day_format)}"
    bill_number = urlparse(url).path.rstrip("/").split("/")[-2] if url.endswith("/text") else urlparse(url).path.rstrip("/").split("/")[-1]
    formatted_bill_number = f"({'S.' if is_senate else 'H.R'} {bill_number})"
    # turning numerical dates into spelled-out date
    summary_date = format_date_into_words(summary_date)

    file_date = get_date_from_text(text, True)

    if file_date is None:
        # add_invalid_url(url)
        return "NA", None, None
    
    filename = f"$H billSums-{file_date}-s{bill_number}" if is_senate else f"$H billSumh-{file_date}-hr{bill_number}"

    if filename_only:
        return filename, None, None
    
    fullname, last_name = get_primary_sponsor(is_senate, 119, bill_number)

    if fullname == "STOP":
        # add_invalid_url(url)
        return "STOP", None, None
    
    if fullname == "" or last_name == "":
        # add_invalid_url(url)
        return "NA", None, None

    prompt = f"""
    Write a 300-word news story about this {'Senate' if is_senate else 'House'} bill, following these rules:

    Headline:
    - Follow this Exact Format: {'Sen.' if is_senate else 'Rep.'} {last_name}s [Last Name] [Bill Name] Analyzed by CRS
    (Do not include the bill number in the headline.)

    [NEWLINE SEPARATOR]

    First Paragraph:
    - DO NOT add any location or dateline at the beginning (e.g., "Washington, D.C. —" or similar).
    - The first sentence must follow this Exact format: [Bill Name], introduced by {'Sen.' if is_senate else 'Rep.'} {fullname} on {summary_date}, has been analyzed by the Congressional Research Service. 
    - Be sure to include **commas before and after the party/state**, e.g., Sen. Jane Doe, D-NY,
    - Immediately follow this sentence with a concise summary of the bill’s purpose in plain, informative language. Prioritize clarity and flow.

    Body:
    - Use structured paragraphs.
    - No quotes.
    - Add context (motivation, impact, background).
    - Do not mention or list any cosponsors or other legislators by name.
    - Focus on the bill’s purpose using the summary mainly, supliment information with the bill text

    Bill Details:
    Summary of the bill:
    {summary}
    Full Bill Text:
    {text}
    Primary Sponsor's Name and State Code: 
    {fullname}
    """

    try:
        # Generate main press release
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=2500
        )
        result = response.choices[0].message.content.strip()
        parts = result.split('\n', 1)

        if len(parts) != 2:
            # add_invalid_url(url)
            print(f"Headline Wasnt Parsed Right")
            return "NA", None, None 

        headline_raw = parts[0]
        body_raw = parts[1]

        headline = clean_text(headline_raw)
        press_body = clean_text(body_raw)

        press_release = press_body.strip()

        # checking to see if program actually added the bill number (patching a known problem)
        if formatted_bill_number not in press_release:
            index = press_release.find(",") # this will be the place to insert the formatted bill number before
            press_release = press_release[:index] + " " + formatted_bill_number + press_release[index:]

        # adding editorial formatting
        press_release = f"WASHINGTON, {today_date} -- {press_release}"

        press_release = clean_text(press_release)
        extract_found_ids(press_release)

        if "[Bill Name]" in press_release:
            return None, None, None
        
        return filename, headline, press_release

    except Exception as e:
        print(f"OpenAI API error: {e}")
        return "NA", None, None

# gets the cosponsor summary (now without the use of the GPT api)
def generate_cosponsor_summary(url, text, is_senate, bill_num):

    intro_date = get_date_from_text(text, False)
    congress_num = 119

    # setting labels determined by is_senate
    label = "S. " if is_senate else "H.R. "
    url_label = "s" if is_senate else "hr"

    # creating the url to be used in the get request
    url = f"https://api.congress.gov/v3/bill/{congress_num}/{url_label}/{bill_num}/cosponsors"  

    # grabbing gov data api key
    api_key = ""
    with open("utils/govkey.txt", "r") as file:
                api_key =  file.readline().strip()
    parameters = {
        "api_key": api_key,
        "limit": 250
    }

    # getting the json response
    try: 
        response = requests.get(url, parameters)

        response.raise_for_status()  # Required to trigger HTTPError

        cosponsors = response.json()['cosponsors']
        urls = [c['url'] for c in cosponsors]

        # print(cosponsors)
        num_cosponsors = len(cosponsors)

    except requests.exceptions.HTTPError as e:
        status = response.status_code
        if status == 502:
            print(f"502 Bad Gateway for URL: {url}")
            return -1
        elif status == 429:
            print(f"429 Too Many Requests for URL: {url}")
            return 429
        else:
            print(f"HTTP error {status} for URL: {url}")
            return -1

    # Adding Reps or Sens
    honorific = ""

    if num_cosponsors == 1:
        honorific = "Sen." if is_senate else "Rep."
    else:
        honorific = "Sens." if is_senate else "Reps."

    # creating and formatting the total paragram
    cosponsors_str = f"The bill ({label}{bill_num}) introduced on {intro_date} has {num_cosponsors} co-sponsors: {honorific} "
    count = 0

    if num_cosponsors == 0:
        cosponsors_str = f"The bill ({label}{bill_num}) was introduced on {intro_date}."
        return cosponsors_str
    
    if num_cosponsors == 1:

        cosponsors_str = f"The bill ({label}{bill_num}) introduced on {intro_date} has {num_cosponsors} co-sponsor: {honorific} "

        try: 
            curr_cosponsor = requests.get(urls[0], parameters)
            member_data = curr_cosponsor.json().get("member", {})
            party = member_data.get("partyHistory", [{}])[0].get("partyAbbreviation", '')
            state = member_data.get("terms", [{}])[-1].get("stateCode", '')  # get the latest term stateCode
            name = member_data.get("directOrderName", '')

        # if it fails, try agian on next scrape
        except Exception as e:
            print(f"Error fetching cosponsor data from {url}: {e}")
            return -1
        
        cosponsors_str += f"{name}, {party}-{state}."

        return cosponsors_str
    
    for url in urls:
        count += 1

        # gettings the direct order name, the party abreviation, and the state code
        try: 
            curr_cosponsor = requests.get(url, parameters)
            member_data = curr_cosponsor.json().get("member", {})
            party = member_data.get("partyHistory", [{}])[0].get("partyAbbreviation", '')
            state = member_data.get("terms", [{}])[-1].get("stateCode", '')  # get the latest term stateCode
            name = member_data.get("directOrderName", '')

        # if it fails, try agian on next scrape
        except Exception as e:
            print(f"Error fetching cosponsor data from {url}: {e}")
            return -1

        # pprint.pp(curr_cosponsor.json())
        if count < num_cosponsors:
            cosponsors_str += f"{name}, {party}-{state}; "
        else:
            cosponsors_str += f"{name}, {party}-{state}."
    return cosponsors_str


def convert_date_format(date_str):
    """
    Convert a date from 'YYYY-MM-DD' to 'MM/DD/YYYY' format.
    
    Args:
        date_str (str): A date string in 'YYYY-MM-DD' format.
        
    Returns:
        str: The date in 'MM/DD/YYYY' format.
    """
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return dt.strftime("%m/%d/%Y")
    except ValueError:
        return "Invalid date format"
