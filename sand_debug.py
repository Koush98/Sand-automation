import json
import logging
import os
from datetime import datetime

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

# ================= LOAD ENV =================
load_dotenv()

PHONE = os.getenv("PHONE")
SECRET = os.getenv("SECRET")
VEHICLE = os.getenv("VEHICLE")
DISTRICT = os.getenv("DISTRICT")
PS = os.getenv("PS")
QTY = os.getenv("QTY")
PURCHASER_NAME = os.getenv("PURCHASER_NAME")
PURCHASER_MOBILE = os.getenv("PURCHASER_MOBILE")
RATE = os.getenv("RATE")

# ================= LOGGING =================
LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)

log_file = os.path.join(LOG_DIR, f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler(log_file, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)

logger = logging.getLogger(__name__)
GENERATE_PASS_SELECTOR = "#ctl00_ContentPlaceHolder1_btn_Proceed"
LOGOUT_SELECTOR = "a[href='../Page/WBMD_Logout.aspx']"

# ================= LOAD JSON =================
with open("dist_ps_map.json", "r", encoding="utf-8") as f:
    mapping = json.load(f)["districts"]


# ================= UTIL =================
class NoRecordsFoundError(Exception):
    pass


def normalize(text):
    return text.strip().lower().replace("-", " ").replace(",", "").replace("&", "")


def validate_inputs():
    logger.info("Validating inputs...")
    required_inputs = {
        "PHONE": PHONE,
        "SECRET": SECRET,
        "VEHICLE": VEHICLE,
        "DISTRICT": DISTRICT,
        "PS": PS,
        "QTY": QTY,
        "PURCHASER_NAME": PURCHASER_NAME,
        "PURCHASER_MOBILE": PURCHASER_MOBILE,
        "RATE": RATE,
    }

    missing = [key for key, value in required_inputs.items() if not str(value or "").strip()]
    if missing:
        raise ValueError(f"Missing required environment variables: {', '.join(missing)}")

    if normalize(DISTRICT) not in mapping:
        raise ValueError(f"Invalid district: {DISTRICT}")


def find_ps(ps_input, ps_map):
    ps_input = normalize(ps_input)

    if ps_input in ps_map:
        return ps_map[ps_input]

    if ps_input + " ps" in ps_map:
        return ps_map[ps_input + " ps"]

    for key in ps_map:
        if ps_input in key:
            return ps_map[key]

    raise ValueError(f"PS not found: {ps_input}")


def slow_type(locator, text):
    locator.click()
    locator.fill("")
    for ch in str(text):
        locator.type(ch, delay=80)


def wait_for_enter(message):
    while True:
        try:
            input(message)
            return
        except KeyboardInterrupt:
            print("\nBrowser is still open. Press ENTER when you want to close it.")


def safe_click(page, selector, name="", timeout=10000):
    matches = page.locator(selector)
    matches.first.wait_for(state="attached", timeout=timeout)

    deadline = page.evaluate("Date.now()") + timeout
    last_error = None

    while page.evaluate("Date.now()") < deadline:
        count = matches.count()

        for index in range(count):
            locator = matches.nth(index)
            try:
                if not locator.is_visible():
                    continue

                locator.scroll_into_view_if_needed()
                locator.click()
                logger.info(f"Clicked: {name or selector}")
                return locator
            except Exception as exc:
                last_error = exc

        page.wait_for_timeout(250)

    raise TimeoutError(
        f"Could not click a visible match for {name or selector}. Last error: {last_error}"
    )


def wait_for_select_value(page, selector, value, name="", timeout=30000):
    dropdown = page.locator(selector)
    dropdown.wait_for(state="visible", timeout=timeout)

    deadline = page.evaluate("Date.now()") + timeout
    option_values = []

    while page.evaluate("Date.now()") < deadline:
        options = dropdown.locator("option")
        option_values = []

        for index in range(options.count()):
            option_values.append(options.nth(index).get_attribute("value") or "")

        if value in option_values:
            logger.info(f"{name or selector} loaded target value: {value}")
            return dropdown

        page.wait_for_timeout(500)

    raise TimeoutError(
        f"{name or selector} did not load target value {value}. Available values: {option_values}"
    )


def wait_for_visible(page, selector, name="", timeout=45000):
    locator = page.locator(selector).first
    locator.wait_for(state="visible", timeout=timeout)
    logger.info(f"Ready: {name or selector}")
    return locator


def capture_debug_artifacts(page):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    screenshot_path = os.path.join(LOG_DIR, f"error_{timestamp}.png")
    html_path = os.path.join(LOG_DIR, f"error_{timestamp}.html")

    page.screenshot(path=screenshot_path, full_page=True)
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(page.content())

    logger.info(f"Screenshot saved: {screenshot_path}")
    logger.info(f"HTML dump saved: {html_path}")
    logger.info(f"Current page URL: {page.url}")
    return screenshot_path, html_path


def handle_popups(page):
    import time

    buttons = ["OK", "Ok", "Confirm & Proceed"]
    logger.info("Checking for popups...")

    for _ in range(5):
        handled = False

        for btn in buttons:
            try:
                locator = page.get_by_role("button", name=btn)
                if locator.is_visible(timeout=2000):
                    locator.click()
                    logger.info(f"Popup clicked: {btn}")
                    time.sleep(1)
                    handled = True
            except Exception:
                pass

        if not handled:
            break


def logout_portal(page):
    try:
        logout_link = wait_for_visible(page, LOGOUT_SELECTOR, "Logout link", timeout=15000)
        logout_link.click()
        page.wait_for_load_state("networkidle")
        handle_popups(page)
        logger.info("Logged out successfully")
        return True
    except Exception as exc:
        logger.warning(f"Logout failed: {exc}")
        return False


def log_available_rows(page):
    qty_count = page.locator("[id$='txt_pass_qty']").count()
    checkbox_count = page.locator("[id$='chkselect']").count()
    logger.info(f"Quantity fields found: {qty_count}")
    logger.info(f"Checkboxes found: {checkbox_count}")


def ensure_records_available(page):
    no_records = page.get_by_text("No Records Found", exact=True)
    if no_records.count() and no_records.first.is_visible():
        raise NoRecordsFoundError(
            "No records found for the selected vehicle, district, and police station."
        )

    qty_count = page.locator("[id$='txt_pass_qty']").count()
    checkbox_count = page.locator("[id$='chkselect']").count()
    if qty_count == 0 or checkbox_count == 0:
        raise NoRecordsFoundError(
            "No selectable quantity rows were loaded on the page."
        )


# ================= MAIN =================
def run():
    logger.info("========== SCRIPT STARTED ==========")

    playwright = None
    browser = None
    context = None
    page = None

    try:
        validate_inputs()

        district_key = normalize(DISTRICT)
        district_data = mapping[district_key]

        district_code = district_data["code"]
        ps_code = find_ps(PS, district_data["ps"])

        logger.info(f"District Code: {district_code}")
        logger.info(f"PS Code: {ps_code}")

        playwright = sync_playwright().start()
        browser = playwright.chromium.launch(headless=False, slow_mo=50)
        context = browser.new_context()
        page = context.new_page()

        logger.info("Opening website...")
        page.goto("https://mdtcl.wb.gov.in/", timeout=60000)

        safe_click(page, "#notice_cl", "Notice")
        safe_click(page, "#img_working_mdo", "MDO")
        page.get_by_role("button", name="SAND").click()

        phone_input = page.locator("input[placeholder='Enter Registered Mobile No.']")
        phone_input.wait_for()
        slow_type(phone_input, PHONE)

        print("Solve CAPTCHA manually...")

        pin_input = page.locator("input[placeholder='Enter Your 6 Digit Secret PIN']")
        pin_input.wait_for(timeout=120000)
        slow_type(pin_input, SECRET)

        page.on("dialog", lambda d: d.dismiss())

        page.get_by_role("button", name="Verify PIN").click()
        page.wait_for_load_state("networkidle")
        handle_popups(page)

        safe_click(page, "a:has-text('Road Challan')", "Road Challan")
        handle_popups(page)

        safe_click(
            page,
            "a[href*='WBMDTCL_TP_Prepare_Draft_Pass.aspx']",
            "Prepare Draft Challan",
        )
        handle_popups(page)

        vehicle_input = wait_for_visible(
            page, "#ctl00_ContentPlaceHolder1_txtVehicleRegNo", "Vehicle field"
        )
        slow_type(vehicle_input, VEHICLE)

        page.locator("#ctl00_ContentPlaceHolder1_ddl_Purchaser_District").select_option(district_code)
        page.get_by_role("button", name="Proceed").click()
        page.wait_for_load_state("networkidle")
        handle_popups(page)

        ps_dropdown = wait_for_select_value(
            page,
            "#ctl00_ContentPlaceHolder1_ddl_PS",
            ps_code,
            name="Police Station dropdown",
            timeout=45000,
        )
        ps_dropdown.select_option(ps_code)
        logger.info(f"Selected PS code: {ps_code}")

        log_available_rows(page)
        ensure_records_available(page)

        qty_input = wait_for_visible(page, "[id$='txt_pass_qty']", "Quantity input")
        slow_type(qty_input, QTY)

        qty_checkbox = wait_for_visible(page, "[id$='chkselect']", "Row checkbox")
        qty_checkbox.check()
        logger.info("Quantity entered and row selected")

        slow_type(page.get_by_role("textbox", name="Enter Purchaser Name"), PURCHASER_NAME)
        slow_type(page.get_by_role("textbox", name="Enter Purchaser Mobile No"), PURCHASER_MOBILE)
        slow_type(page.locator("#ctl00_ContentPlaceHolder1_txt_sand_rate"), RATE)

        page.get_by_role("button", name="Save Draft").click()
        logger.info("Draft saved")

        print("Draft created")
        wait_for_enter("Verify manually -> Press ENTER")

        safe_click(page, GENERATE_PASS_SELECTOR, "Proceed To Generate Pass", timeout=15000)
        page.wait_for_load_state("networkidle")
        handle_popups(page)
        logger.info("Pass generated")

        if not logout_portal(page):
            raise RuntimeError("Logout did not complete, so the browser should not be closed.")

        print("DONE")
        wait_for_enter("Logged out successfully -> Press ENTER to close browser...")

    except NoRecordsFoundError as exc:
        logger.warning(str(exc))

        if page:
            try:
                screenshot_path, html_path = capture_debug_artifacts(page)
                print(f"No records found. Screenshot saved: {screenshot_path}")
                print(f"HTML dump saved: {html_path}")
                print(f"Current URL: {page.url}")
            except Exception:
                logger.exception("Failed to capture debug artifacts")

        print("No records were available on the portal, so the script stopped without filling quantity.")
        wait_for_enter("Check the page manually -> Press ENTER when you want to close...")

    except Exception:
        logger.exception("CRITICAL ERROR OCCURRED")

        if page:
            try:
                screenshot_path, html_path = capture_debug_artifacts(page)
                print(f"Screenshot saved: {screenshot_path}")
                print(f"HTML dump saved: {html_path}")
                print(f"Current URL: {page.url}")
            except Exception:
                logger.exception("Failed to capture debug artifacts")

        print("Script failed. Browser is still open for debugging.")
        wait_for_enter("Fix manually -> Press ENTER when you want to close...")

    finally:
        if context:
            context.close()
        if browser:
            browser.close()
        if playwright:
            playwright.stop()
        logger.info("========== SCRIPT ENDED ==========")


if __name__ == "__main__":
    run()
