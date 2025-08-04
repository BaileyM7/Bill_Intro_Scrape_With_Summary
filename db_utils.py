import sys
import yaml
import logging
import openai_api
import mysql.connector
from datetime import datetime
from db_utils import get_db_connection
from mysql.connector import IntegrityError, DataError
from url_processing import get_most_recent_bill_number


def get_db_connection(yml_path="configs/db_config.yml"):
    with open(yml_path, "r") as yml_file:
        config = yaml.load(yml_file, Loader=yaml.FullLoader)
    return mysql.connector.connect(
        host=config["host"],
        user=config["user"],
        password=config["password"],
        database=config["database"]
    )

def get_max_bill_number_from_db(chamber):
    """Returns the highest bill number in the database for the given chamber."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT MAX(CAST(SUBSTRING_INDEX(url, '/', -1) AS UNSIGNED))
            FROM url_queue
            WHERE chamber = %s
        """, (chamber,))
        result = cursor.fetchone()[0]
        logging.debug(f"{chamber}: MAX CURRENT BILL NUM => {result}")

        return result if result else 0
    finally:
        conn.close()

def insert_new_bills(chamber, last_known, latest_number):
    """Inserts new bill URLs into the queue based on the difference between latest and known max."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        base_url = f"https://www.congress.gov/bill/119th-congress/{chamber}-bill/"
        for num in range(last_known + 1, latest_number + 1):
            url = base_url + str(num)
            try:
                logging.debug(f"TRYING TO INSERT new {chamber} bill: {num}")
                cursor.execute("""
                    INSERT INTO url_queue (url, chamber, status)
                    VALUES (%s, %s, 'pending')
                """, (url, chamber))

                logging.debug(f"Insert success: {url}")
            except Exception as e:
                logging.debug(f"Failed to insert {url}: {e}")
        conn.commit()
        logging.debug(f"Inserted {latest_number - last_known} new {chamber} bill URLs.")
    finally:
        conn.close()

def populateDB():
    """Main function to find the latest House and Senate bill numbers and queue missing ones."""

    house_latest = get_most_recent_bill_number(False)
    senate_latest = get_most_recent_bill_number(True)
    
    if house_latest != -1:
        current_max_house = get_max_bill_number_from_db("house")
        if house_latest > current_max_house:
            insert_new_bills("house", current_max_house, house_latest)

    if senate_latest != -1:
        current_max_senate = get_max_bill_number_from_db("senate")
        if senate_latest > current_max_senate:
            insert_new_bills("senate", current_max_senate, senate_latest)

# --- Insert Story Function ---
def insert_story(filename, headline, body, a_id, sponsor_blob):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Check for duplicate filename
        check_sql = "SELECT COUNT(*) FROM story WHERE filename = %s"
        cursor.execute(check_sql, (filename,))
        if cursor.fetchone()[0] > 0:
            logging.info(f"Duplicate filename, skipping: {filename}")
            return False

        # Insert into story
        insert_sql = """
        INSERT INTO story
        (filename, uname, source, by_line, headline, story_txt, editor, invoice_tag,
         date_sent, sent_to, wire_to, nexis_sent, factiva_sent,
         status, content_date, last_action, orig_txt)
        VALUES (%s, %s, %s, %s, %s, %s, '', '', NOW(), '', '', NULL, NULL, %s, %s, SYSDATE(), %s)
        """
        today_str = datetime.now().strftime('%Y-%m-%d')
        cursor.execute(insert_sql, (
            filename,
            "T70-BM-BillSum",
            a_id,
            "Bailey Malota",
            headline,
            body,
            'D',
            today_str,
            sponsor_blob
        ))

        # Get story ID s_id
        s_id = cursor.lastrowid

        # Insert state tags into story_tag
        tag_insert_sql = "INSERT INTO story_tag (id, tag_id) VALUES (%s, %s)"
        for state_abbr, tag_id in openai_api.found_ids.items():
            cursor.execute(tag_insert_sql, (s_id, tag_id))
            logging.debug(f"Inserted tag for state {state_abbr} (tag_id={tag_id})")

        conn.commit()
        logging.info(f"Inserted story and {len(openai_api.found_ids)} tag(s): {filename}")
        return s_id
    except Exception as err:
        logging.error(f"DB insert failed: {err}")
        return None
    finally:
        if conn:
            conn.close()

# --- Load Sources SQL Dump ---
def load_sources_sql(filepath="sources.dmp.sql"):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        with open(filepath, 'r', encoding='utf-8') as f:
            statement = ""
            for line in f:
                if line.strip().startswith("--") or line.strip() == '':
                    continue
                statement += line
                if line.strip().endswith(";"):
                    try:
                        cursor.execute(statement)
                    except Exception as e:
                        logging.warning(f"skipped SQL chunk due to error: {e}\n{statement.strip()}")
                    statement = ""
        conn.commit()
        logging.info("Loaded sources.dmp.sql successfully")
    except Exception as e:
        logging.error(f"Failed to load SQL file: {e}")
        sys.exit(1)
    finally:
        if conn:
            conn.close()


def populateCsv(num_range):
    