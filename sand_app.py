import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from playwright.sync_api import Locator, Page, Playwright, sync_playwright


BASE_URL = "https://mdtcl.wb.gov.in/"
DISTRICT_SELECTOR = "#ctl00_ContentPlaceHolder1_ddl_Purchaser_District"
PS_SELECTOR = "#ctl00_ContentPlaceHolder1_ddl_PS"
VEHICLE_SELECTOR = "#ctl00_ContentPlaceHolder1_txtVehicleRegNo"
RATE_SELECTOR = "#ctl00_ContentPlaceHolder1_txt_sand_rate"
LOG_DIR = Path("logs")
MAP_FILE = Path("dist_ps_map.json")


@dataclass(frozen=True)
class Config:
    phone: str
    secret: str
    vehicle: str
    district: str
    ps: str
    qty: str
    purchaser_name: str
    purchaser_mobile: str
    rate: str


class PortalAutomationError(Exception):
    pass


class NoRecordsFoundError(PortalAutomationError):
    pass


def setup_logging() -> logging.Logger:
    LOG_DIR.mkdir(exist_ok=True)
    log_file = LOG_DIR / f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(),
        ],
        force=True,
    )
    return logging.getLogger(__name__)


logger = setup_logging()


def normalize(text: str) -> str:
    return (
        str(text or "")
        .strip()
        .lower()
        .replace("-", " ")
        .replace(",", "")
        .replace("&", "")
    )


def load_mapping() -> dict:
    with MAP_FILE.open("r", encoding="utf-8") as file:
        payload = json.load(file)

    districts = payload.get("districts")
    if not isinstance(districts, dict) or not districts:
        raise PortalAutomationError(f"Invalid mapping file: {MAP_FILE}")
    return districts


def load_config(mapping: dict) -> Config:
    load_dotenv()

    env_map = {
        "phone": os.getenv("PHONE"),
        "secret": os.getenv("SECRET"),
        "vehicle": os.getenv("VEHICLE"),
        "district": os.getenv("DISTRICT"),
        "ps": os.getenv("PS"),
        "qty": os.getenv("QTY"),
        "purchaser_name": os.getenv("PURCHASER_NAME"),
        "purchaser_mobile": os.getenv("PURCHASER_MOBILE"),
        "rate": os.getenv("RATE"),
    }

    missing = [key.upper() for key, value in env_map.items() if not str(value or "").strip()]
    if missing:
        raise ValueError(f"Missing required environment variables: {', '.join(missing)}")

    if normalize(env_map["district"]) not in mapping:
        raise ValueError(f"Invalid district: {env_map['district']}")

    return Config(**{key: str(value).strip() for key, value in env_map.items()})


def find_ps_code(ps_input: str, ps_map: dict) -> str:
    normalized_input = normalize(ps_input)

    if normalized_input in ps_map:
        return ps_map[normalized_input]

    if normalized_input + " ps" in ps_map:
        return ps_map[normalized_input + " ps"]

    for key, value in ps_map.items():
        if normalized_input in key:
            return value

    raise ValueError(f"Police station not found: {ps_input}")


def wait_for_enter(message: str) -> None:
    while True:
        try:
            input(message)
            return
        except KeyboardInterrupt:
            print("\nBrowser is still open. Press ENTER when you want to close it.")


def slow_type(locator: Locator, text: str) -> None:
    locator.click()
    locator.fill("")
    for char in str(text):
        locator.type(char, delay=80)


def safe_click(page: Page, selector: str, name: str, timeout: int = 10000) -> Locator:
    matches = page.locator(selector)
    matches.first.wait_for(state="attached", timeout=timeout)

    deadline = page.evaluate("Date.now()") + timeout
    last_error = None

    while page.evaluate("Date.now()") < deadline:
        for index in range(matches.count()):
            locator = matches.nth(index)
            try:
                if not locator.is_visible():
                    continue

                locator.scroll_into_view_if_needed()
                locator.click()
                logger.info("Clicked: %s", name)
                return locator
            except Exception as exc:
                last_error = exc

        page.wait_for_timeout(250)

    raise TimeoutError(f"Could not click {name}. Last error: {last_error}")


def wait_for_visible(page: Page, selector: str, name: str, timeout: int = 45000) -> Locator:
    locator = page.locator(selector).first
    locator.wait_for(state="visible", timeout=timeout)
    logger.info("Ready: %s", name)
    return locator


def wait_for_select_value(
    page: Page, selector: str, value: str, name: str, timeout: int = 45000
) -> Locator:
    dropdown = page.locator(selector)
    dropdown.wait_for(state="visible", timeout=timeout)

    deadline = page.evaluate("Date.now()") + timeout
    last_values = []

    while page.evaluate("Date.now()") < deadline:
        options = dropdown.locator("option")
        last_values = [
            options.nth(index).get_attribute("value") or ""
            for index in range(options.count())
        ]

        if value in last_values:
            logger.info("%s loaded target value: %s", name, value)
            return dropdown

        page.wait_for_timeout(500)

    raise TimeoutError(f"{name} did not load value {value}. Available values: {last_values}")


def handle_popups(page: Page) -> None:
    buttons = ["OK", "Ok", "Confirm & Proceed"]
    logger.info("Checking for popups...")

    for _ in range(5):
        handled = False
        for button_name in buttons:
            try:
                locator = page.get_by_role("button", name=button_name)
                if locator.is_visible(timeout=2000):
                    locator.click()
                    logger.info("Popup clicked: %s", button_name)
                    page.wait_for_timeout(1000)
                    handled = True
            except Exception:
                continue

        if not handled:
            return


def log_available_rows(page: Page) -> None:
    qty_count = page.locator("[id$='txt_pass_qty']").count()
    checkbox_count = page.locator("[id$='chkselect']").count()
    logger.info("Quantity fields found: %s", qty_count)
    logger.info("Checkboxes found: %s", checkbox_count)


def ensure_records_available(page: Page) -> None:
    no_records = page.get_by_text("No Records Found", exact=True)
    if no_records.count() and no_records.first.is_visible():
        raise NoRecordsFoundError(
            "No records found for the selected vehicle, district, and police station."
        )

    qty_count = page.locator("[id$='txt_pass_qty']").count()
    checkbox_count = page.locator("[id$='chkselect']").count()
    if qty_count == 0 or checkbox_count == 0:
        raise NoRecordsFoundError("No selectable quantity rows were loaded on the page.")


def capture_debug_artifacts(page: Page) -> tuple[Path, Path]:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    screenshot_path = LOG_DIR / f"error_{timestamp}.png"
    html_path = LOG_DIR / f"error_{timestamp}.html"

    page.screenshot(path=str(screenshot_path), full_page=True)
    html_path.write_text(page.content(), encoding="utf-8")

    logger.info("Screenshot saved: %s", screenshot_path)
    logger.info("HTML dump saved: %s", html_path)
    logger.info("Current page URL: %s", page.url)
    return screenshot_path, html_path


def fill_login(page: Page, config: Config) -> None:
    safe_click(page, "#notice_cl", "Notice")
    safe_click(page, "#img_working_mdo", "MDO")
    page.get_by_role("button", name="SAND").click()

    phone_input = wait_for_visible(
        page,
        "input[placeholder='Enter Registered Mobile No.']",
        "Phone input",
    )
    slow_type(phone_input, config.phone)

    print("Solve CAPTCHA manually...")

    pin_input = wait_for_visible(
        page,
        "input[placeholder='Enter Your 6 Digit Secret PIN']",
        "PIN input",
        timeout=120000,
    )
    slow_type(pin_input, config.secret)

    page.on("dialog", lambda dialog: dialog.dismiss())
    page.get_by_role("button", name="Verify PIN").click()
    page.wait_for_load_state("networkidle")
    handle_popups(page)


def navigate_to_draft_page(page: Page) -> None:
    safe_click(page, "a:has-text('Road Challan')", "Road Challan")
    handle_popups(page)
    safe_click(
        page,
        "a[href*='WBMDTCL_TP_Prepare_Draft_Pass.aspx']",
        "Prepare Draft Challan",
    )
    handle_popups(page)


def fill_draft_form(page: Page, config: Config, district_code: str, ps_code: str) -> None:
    vehicle_input = wait_for_visible(page, VEHICLE_SELECTOR, "Vehicle field")
    slow_type(vehicle_input, config.vehicle)

    page.locator(DISTRICT_SELECTOR).select_option(district_code)
    page.get_by_role("button", name="Proceed").click()
    page.wait_for_load_state("networkidle")
    handle_popups(page)

    ps_dropdown = wait_for_select_value(page, PS_SELECTOR, ps_code, "Police Station dropdown")
    ps_dropdown.select_option(ps_code)
    logger.info("Selected PS code: %s", ps_code)

    log_available_rows(page)
    ensure_records_available(page)

    qty_input = wait_for_visible(page, "[id$='txt_pass_qty']", "Quantity input")
    slow_type(qty_input, config.qty)

    qty_checkbox = wait_for_visible(page, "[id$='chkselect']", "Row checkbox")
    qty_checkbox.check()
    logger.info("Quantity entered and row selected")

    slow_type(page.get_by_role("textbox", name="Enter Purchaser Name"), config.purchaser_name)
    slow_type(
        page.get_by_role("textbox", name="Enter Purchaser Mobile No"),
        config.purchaser_mobile,
    )
    slow_type(page.locator(RATE_SELECTOR), config.rate)


def save_and_generate(page: Page) -> None:
    page.get_by_role("button", name="Save Draft").click()
    logger.info("Draft saved")

    print("Draft created")
    wait_for_enter("Verify manually -> Press ENTER")

    page.get_by_role("button", name="Proceed To Generate Pass").click()
    logger.info("Pass generated")
    print("DONE")
    wait_for_enter("Press ENTER to close browser...")


def run_portal_job(playwright: Playwright, config: Config, mapping: dict) -> None:
    district_key = normalize(config.district)
    district_data = mapping[district_key]
    district_code = district_data["code"]
    ps_code = find_ps_code(config.ps, district_data["ps"])

    logger.info("District Code: %s", district_code)
    logger.info("PS Code: %s", ps_code)

    browser = playwright.chromium.launch(headless=False, slow_mo=50)
    context = browser.new_context()
    page = context.new_page()

    try:
        logger.info("Opening website...")
        page.goto(BASE_URL, timeout=60000)

        fill_login(page, config)
        navigate_to_draft_page(page)
        fill_draft_form(page, config, district_code, ps_code)
        save_and_generate(page)

    except NoRecordsFoundError as exc:
        logger.warning("%s", exc)
        screenshot_path, html_path = capture_debug_artifacts(page)
        print(f"No records found. Screenshot saved: {screenshot_path}")
        print(f"HTML dump saved: {html_path}")
        print(f"Current URL: {page.url}")
        print("No records were available on the portal, so the script stopped before filling the draft.")
        wait_for_enter("Check the page manually -> Press ENTER when you want to close...")

    except Exception:
        logger.exception("CRITICAL ERROR OCCURRED")
        try:
            screenshot_path, html_path = capture_debug_artifacts(page)
            print(f"Screenshot saved: {screenshot_path}")
            print(f"HTML dump saved: {html_path}")
            print(f"Current URL: {page.url}")
        except Exception:
            logger.exception("Failed to capture debug artifacts")

        print("Script failed. Browser is still open for debugging.")
        wait_for_enter("Fix manually -> Press ENTER when you want to close...")
        raise

    finally:
        context.close()
        browser.close()


def main() -> int:
    logger.info("========== SCRIPT STARTED ==========")

    try:
        mapping = load_mapping()
        config = load_config(mapping)

        with sync_playwright() as playwright:
            run_portal_job(playwright, config, mapping)
        return 0

    except Exception:
        logger.exception("SCRIPT ENDED WITH ERROR")
        return 1

    finally:
        logger.info("========== SCRIPT ENDED ==========")


if __name__ == "__main__":
    raise SystemExit(main())


def run(config: Config, mapping: dict | None = None) -> None:
    resolved_mapping = mapping or load_mapping()
    with sync_playwright() as playwright:
        run_portal_job(playwright, config, resolved_mapping)
