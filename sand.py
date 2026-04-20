"""
Legacy implementation retained for reference.
`python sand.py` now delegates to `sand_app.main()`.
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from playwright.sync_api import Locator, Page, Playwright, sync_playwright

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
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

# ================= LOAD JSON =================
with open("dist_ps_map.json", "r", encoding="utf-8") as f:
    mapping = json.load(f)["districts"]

# ================= UTIL =================
def normalize(text):
    return text.strip().lower().replace("-", " ").replace(",", "").replace("&", "")

def validate_inputs():
    logger.info("Validating inputs...")
    if not all([PHONE, SECRET, VEHICLE, DISTRICT, PS]):
        raise ValueError("Missing required environment variables")

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
    for ch in text:
        locator.type(ch, delay=80)

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
                return
            except Exception as exc:
                last_error = exc

        page.wait_for_timeout(250)

    raise TimeoutError(
        f"Could not click a visible match for {name or selector}. Last error: {last_error}"
    )

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
            except:
                pass

        if not handled:
            break

# ================= MAIN =================
def run():
    logger.info("========== SCRIPT STARTED ==========")

    browser = None
    page = None

    try:
        validate_inputs()

        district_key = normalize(DISTRICT)
        district_data = mapping[district_key]

        district_code = district_data["code"]
        ps_code = find_ps(PS, district_data["ps"])

        logger.info(f"District Code: {district_code}")
        logger.info(f"PS Code: {ps_code}")

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False, slow_mo=50)
            context = browser.new_context()
            page = context.new_page()

            logger.info("Opening website...")
            page.goto("https://mdtcl.wb.gov.in/", timeout=60000)

            # Navigation
            safe_click(page, "#notice_cl", "Notice")
            safe_click(page, "#img_working_mdo", "MDO")
            page.get_by_role("button", name="SAND").click()

            # Phone
            phone_input = page.locator("input[placeholder='Enter Registered Mobile No.']")
            phone_input.wait_for()
            slow_type(phone_input, PHONE)

            print("👉 Solve CAPTCHA manually...")

            # PIN
            pin_input = page.locator("input[placeholder='Enter Your 6 Digit Secret PIN']")
            pin_input.wait_for(timeout=120000)
            slow_type(pin_input, SECRET)

            page.on("dialog", lambda d: d.dismiss())

            page.get_by_role("button", name="Verify PIN").click()
            page.wait_for_load_state("networkidle")

            handle_popups(page)

            # Navigation
            safe_click(page, "a:has-text('Road Challan')", "Road Challan")
            handle_popups(page)

            safe_click(
                page,
                "a[href*='WBMDTCL_TP_Prepare_Draft_Pass.aspx']",
                "Prepare Draft Challan"
            )
            handle_popups(page)

            # Vehicle
            vehicle_input = page.locator("#ctl00_ContentPlaceHolder1_txtVehicleRegNo")
            vehicle_input.wait_for()
            slow_type(vehicle_input, VEHICLE)

            # District
            page.locator("#ctl00_ContentPlaceHolder1_ddl_Purchaser_District").select_option(district_code)
            page.get_by_role("button", name="Proceed").click()

            # Wait for PS properly
            page.locator("#ctl00_ContentPlaceHolder1_ddl_PS option").nth(1).wait_for()

            # PS
            page.locator("#ctl00_ContentPlaceHolder1_ddl_PS").select_option(ps_code)

            # Quantity
            qty_input = page.locator("#ctl00_ContentPlaceHolder1_GridView2_ctl02_txt_pass_qty")
            qty_input.wait_for()
            slow_type(qty_input, QTY)

            page.locator("#ctl00_ContentPlaceHolder1_GridView2_ctl02_chkselect").check()

            # Purchaser
            slow_type(page.get_by_role("textbox", name="Enter Purchaser Name"), PURCHASER_NAME)
            slow_type(page.get_by_role("textbox", name="Enter Purchaser Mobile No"), PURCHASER_MOBILE)

            slow_type(page.locator("#ctl00_ContentPlaceHolder1_txt_sand_rate"), RATE)

            # Save
            page.get_by_role("button", name="Save Draft").click()
            logger.info("Draft saved")

            print("✅ Draft created")
            input("Verify manually → Press ENTER")

            page.get_by_role("button", name="Proceed To Generate Pass").click()
            logger.info("Pass generated")

            print("🎉 DONE")

            input("Press ENTER to close browser...")
            browser.close()

    except Exception:
        logger.exception("CRITICAL ERROR OCCURRED")

        if page:
            try:
                page.screenshot(path="error.png")
                logger.info("📸 Screenshot saved")
            except:
                pass

        print("❌ Script failed. Browser is STILL OPEN for debugging.")
        input("Fix manually → Press ENTER when you want to close...")

        if browser:
            browser.close()

    finally:
        logger.info("========== SCRIPT ENDED ==========")


"""

if __name__ == "__main__":
    from sand_app import main

    raise SystemExit(main())
