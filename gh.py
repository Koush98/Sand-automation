import json
from playwright.sync_api import sync_playwright

DISTRICT_SELECTOR = "#ctl00_ContentPlaceHolder1_ddl_Purchaser_District"
PS_SELECTOR = "#ctl00_ContentPlaceHolder1_ddl_PS"


def wait_for_draft_page(page):
    """Wait until draft challan page is actually ready"""

    print("⏳ Waiting for Draft Page...")

    for _ in range(60):  # retry for ~60 seconds
        try:
            if page.locator(DISTRICT_SELECTOR).count() > 0:
                print("✅ Draft page detected")
                return True
        except:
            pass

        # Handle popups if they appear
        try:
            if page.get_by_role("button", name="OK").count() > 0:
                page.get_by_role("button", name="OK").click()
        except:
            pass

        try:
            if page.get_by_role("button", name="Confirm & Proceed").count() > 0:
                page.get_by_role("button", name="Confirm & Proceed").click()
        except:
            pass

        page.wait_for_timeout(1000)

    raise Exception("❌ Draft page not detected")


def wait_for_ps_update(page, previous_count):
    try:
        page.wait_for_function(
            """(selector, prevCount) => {
                const ps = document.querySelector(selector);
                return ps && ps.options.length > 1 && ps.options.length !== prevCount;
            }""",
            arg=(PS_SELECTOR, previous_count),
            timeout=10000
        )
    except:
        page.wait_for_timeout(2000)


def extract_mapping(page):
    mapping = {}

    districts = page.locator(f"{DISTRICT_SELECTOR} option").all()

    for district in districts:
        d_name = district.inner_text().strip()
        d_code = district.get_attribute("value")

        if not d_code or d_code == "0":
            continue

        print(f"📍 {d_name}")

        previous_ps_count = page.locator(f"{PS_SELECTOR} option").count()

        page.locator(DISTRICT_SELECTOR).select_option(d_code)

        wait_for_ps_update(page, previous_ps_count)

        ps_elements = page.locator(f"{PS_SELECTOR} option").all()

        ps_map = {}
        for ps in ps_elements:
            ps_name = ps.inner_text().strip()
            ps_code = ps.get_attribute("value")

            if ps_code and ps_code != "0":
                ps_map[ps_name] = ps_code

        print(f"   ✅ {len(ps_map)} PS")

        mapping[d_name] = {
            "code": d_code,
            "ps": ps_map
        }

    return mapping


def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()

        page.goto("https://mdtcl.wb.gov.in/")

        print("\n👉 Login manually + go to Draft Challan page")

        # 🔥 NEW: Safe wait instead of wait_for_selector
        wait_for_draft_page(page)

        print("\n🚀 Starting extraction...\n")

        data = extract_mapping(page)

        with open("full_mapping.json", "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        print("\n🎉 DONE! Saved full_mapping.json")

        input("\nPress ENTER to close...")
        browser.close()


run()