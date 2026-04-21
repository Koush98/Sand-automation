from playwright.async_api import Page

from session_service.domain import SessionStatus


COOLDOWN_TEXT_MARKERS = [
    "20 min",
    "20 minutes",
    "already logged in",
    "already login",
    "not properly logout",
    "not properly log out",
    "please try after 20 min",
    "please try after 20 minutes",
]
LOGOUT_SELECTOR = "a[href='../Page/WBMD_Logout.aspx']"


async def slow_type(locator, text: str) -> None:
    await locator.click()
    await locator.fill("")
    for char in str(text):
        await locator.type(char, delay=80)


async def dismiss_portal_popups(page: Page) -> None:
    button_names = ["OK", "Ok", "Confirm & Proceed"]

    for _ in range(5):
        handled = False
        for button_name in button_names:
            locator = page.get_by_role("button", name=button_name)
            try:
                if await locator.count() > 0 and await locator.first.is_visible():
                    await locator.first.click()
                    await page.wait_for_timeout(800)
                    handled = True
            except Exception:
                continue
        if not handled:
            return


async def prepare_portal_entry(page: Page) -> None:
    await dismiss_portal_popups(page)

    notice_close = page.locator("#notice_cl")
    try:
        if await notice_close.count() > 0 and await notice_close.first.is_visible():
            await notice_close.first.click()
            await page.wait_for_timeout(500)
    except Exception:
        pass

    await dismiss_portal_popups(page)

    mdo_tile = page.locator("#img_working_mdo")
    try:
        if await mdo_tile.count() > 0 and await mdo_tile.first.is_visible():
            await mdo_tile.first.click()
            await page.wait_for_timeout(800)
    except Exception:
        pass

    sand_button = page.get_by_role("button", name="SAND")
    try:
        if await sand_button.count() > 0 and await sand_button.first.is_visible():
            await sand_button.first.click()
            await page.wait_for_timeout(1200)
    except Exception:
        pass

    await dismiss_portal_popups(page)


async def prime_login_flow(page: Page, phone: str, secret: str = None) -> None:
    phone_input = page.locator("input[placeholder='Enter Registered Mobile No.']")
    if await phone_input.count() > 0 and await phone_input.first.is_visible():
        current_value = await phone_input.first.input_value()
        if current_value.strip() != str(phone).strip():
            await slow_type(phone_input.first, phone)

    if not secret:
        return

    pin_input = page.locator("input[placeholder='Enter Your 6 Digit Secret PIN']")
    try:
        await pin_input.first.wait_for(state="visible", timeout=120000)
    except Exception:
        return

    await slow_type(pin_input.first, secret)
    page.on("dialog", lambda dialog: dialog.dismiss())

    verify_pin = page.get_by_role("button", name="Verify PIN")
    if await verify_pin.count() > 0 and await verify_pin.first.is_visible():
        await verify_pin.first.click()
        await page.wait_for_load_state("networkidle")
        await dismiss_portal_popups(page)


async def logout_portal(page: Page) -> bool:
    exact_logout = page.locator(LOGOUT_SELECTOR)

    try:
        if await exact_logout.count() > 0 and await exact_logout.first.is_visible():
            await exact_logout.first.click()
            await page.wait_for_load_state("networkidle")
            await dismiss_portal_popups(page)
            status, portal_state, _, login_screen_visible = await detect_portal_state(page)
            if login_screen_visible or portal_state in {"login_screen", "pin_required"}:
                return True
    except Exception:
        pass

    fallback_candidates = [
        page.get_by_role("link", name="Logout"),
        page.get_by_role("link", name="Log Out"),
        page.get_by_role("button", name="Logout"),
        page.get_by_role("button", name="Log Out"),
        page.locator("a:has-text('Logout')"),
        page.locator("a:has-text('Log Out')"),
        page.locator("input[value='Logout']"),
        page.locator("input[value='Log Out']"),
    ]

    for locator in fallback_candidates:
        try:
            if await locator.count() > 0 and await locator.first.is_visible():
                await locator.first.click()
                await page.wait_for_load_state("networkidle")
                await dismiss_portal_popups(page)
                status, portal_state, _, login_screen_visible = await detect_portal_state(page)
                if login_screen_visible or portal_state in {"login_screen", "pin_required"}:
                    return True
        except Exception:
            continue

    return False


async def detect_portal_state(page: Page) -> tuple[SessionStatus, str, bool, bool]:
    phone_input = page.locator("input[placeholder='Enter Registered Mobile No.']")
    pin_input = page.locator("input[placeholder='Enter Your 6 Digit Secret PIN']")
    road_challan_link = page.locator("a:has-text('Road Challan')")
    district_dropdown = page.locator("#ctl00_ContentPlaceHolder1_ddl_Purchaser_District")
    page_text = ""

    try:
        page_text = (await page.locator("body").inner_text()).lower()
    except Exception:
        page_text = ""

    if any(marker in page_text for marker in COOLDOWN_TEXT_MARKERS):
        return SessionStatus.cooldown, "portal_cooldown_message", False, False

    if await district_dropdown.count() > 0 and await district_dropdown.first.is_visible():
        return SessionStatus.logged_in, "draft_page", True, False

    if await road_challan_link.count() > 0 and await road_challan_link.first.is_visible():
        return SessionStatus.logged_in, "dashboard", True, False

    if await pin_input.count() > 0 and await pin_input.first.is_visible():
        return SessionStatus.needs_login, "pin_required", False, True

    if await phone_input.count() > 0 and await phone_input.first.is_visible():
        return SessionStatus.needs_login, "login_screen", False, True

    return SessionStatus.idle, "unknown", False, False
