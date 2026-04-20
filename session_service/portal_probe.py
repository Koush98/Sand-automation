from playwright.async_api import Page

from session_service.domain import SessionStatus


async def detect_portal_state(page: Page) -> tuple[SessionStatus, str, bool, bool]:
    phone_input = page.locator("input[placeholder='Enter Registered Mobile No.']")
    pin_input = page.locator("input[placeholder='Enter Your 6 Digit Secret PIN']")
    road_challan_link = page.locator("a:has-text('Road Challan')")
    district_dropdown = page.locator("#ctl00_ContentPlaceHolder1_ddl_Purchaser_District")

    if await district_dropdown.count() > 0 and await district_dropdown.first.is_visible():
        return SessionStatus.logged_in, "draft_page", True, False

    if await road_challan_link.count() > 0 and await road_challan_link.first.is_visible():
        return SessionStatus.logged_in, "dashboard", True, False

    if await pin_input.count() > 0 and await pin_input.first.is_visible():
        return SessionStatus.needs_login, "pin_required", False, True

    if await phone_input.count() > 0 and await phone_input.first.is_visible():
        return SessionStatus.needs_login, "login_screen", False, True

    return SessionStatus.idle, "unknown", False, False
