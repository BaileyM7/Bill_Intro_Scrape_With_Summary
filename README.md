# Bill\_Intro\_Scrape\_With\_Summary

This project automates the process of collecting, summarizing, and storing newly introduced U.S. congressional bills from both the House and Senate. Once a bill has complete data (text, summary, and cosponsors), it uses the OpenAI API to generate a press release-style summary and stores it in a MySQL database for future retrieval and analysis.

---

## 🚀 Features

* Detects and processes newly introduced House and Senate bills
* Scrapes bill text, summary, and sponsor details via Congress.gov API and backup sources
* Uses OpenAI GPT to generate press releases with headlines and structured summaries
* Inserts results into a MySQL database with duplicate handling
* Logs all activities and errors
* Command-line interface with flexible options for reprocessing and testing

---

## 📁 Project Structure

* `main.py` – Entry point for bill scraping, processing, and database insertion
* `openai_api.py` – Manages OpenAI API calls for summary generation
* `url_processing.py` – Handles scraping and parsing of bill text, summary, and sponsor info
* `db_utils.py` – Connects to the MySQL database and performs insert/update operations
* `README.md` – Project documentation

---

## ⚙️ Usage

```bash
python main.py [options]
```

### Options

| Option             | Description                                                                 |
| ------------------ | --------------------------------------------------------------------------- |
| `-t <start> <end>` | Test mode — generate summaries for bill IDs in the specified range and exit |
| `-p`               | Populate the database with the latest bill list before processing           |
| `-s`               | Process Senate bills only                                                   |
| `-h`               | Process House bills only                                                    |

Note:

* `-t` cannot be used in combination with `-p`, `-s`, or `-h`
* If `-t` is used, it must be followed by two integers specifying the range of bill numbers

---

## 🧠 How It Works

1. **Bill Detection**:

   * Pulls the latest bill numbers for House and Senate via the Congress.gov API.

2. **Data Extraction**:

   * Fetches the bill text and summary via the API.
   * Falls back to HTML scraping if API content is unavailable.

3. **Sponsor Parsing**:

   * Extracts the primary sponsor's name and affiliation for attribution in the summary.

4. **Summary Generation**:

   * Calls OpenAI GPT API with structured prompts.
   * Outputs a headline and formatted press release text.

5. **Database Insertion**:

   * Inserts bill metadata and AI-generated summaries into a MySQL table.
   * Handles duplicates, retries, and logging.

---

## 🔧 Setup

1. Install dependencies:

2. Configure database credentials in:

   ```
   configs/db_config.yml
   ```

3. Add your OpenAI API key to:

   ```
   utils/govkey.txt
   ```

---

## 🧪 Example

```bash
python main.py -t 100 105
```

Generates summaries for bills in the range 100 to 105 in test mode and prints them to the console without inserting into the database.

```bash
python main.py -p -s
```

Populates the latest bill list and processes Senate bills only.

---