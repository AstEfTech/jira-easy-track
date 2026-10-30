from capture import snap, hold, move, click, type_in, scroll_to


def run(page):
    nav = lambda n: page.locator(f'#nav button[data-tab="{n}"]')
    btn_txt = lambda sel: page.locator(sel).inner_text()

    # 1. Setup
    click(page, nav('conn'))
    hold(page, 1300)
    click(page, page.locator('#c-test'))
    page.wait_for_timeout(600)
    for _ in range(3):
        snap(page, 300)
    click(page, page.locator('#c-savecfg'))
    page.wait_for_timeout(700)
    hold(page, 1500)

    # 2. Tasks
    click(page, nav('tasks'))
    hold(page, 1500)
    # period
    click(page, page.locator('details.fold:has(#s-per-sum) > summary'))
    hold(page, 1200)
    click(page, page.locator('details.fold:has(#s-per-sum) > summary'))
    click(page, page.locator('#k-load'))
    page.wait_for_selector('#k-table tr:nth-child(4)')
    page.wait_for_timeout(800)
    hold(page, 1300)

    type_in(page, page.locator('input[data-k="KAN-3"][data-f="total"]'), '4')
    page.select_option('select[data-k="KAN-3"][data-f="shift"]', 'start')
    snap(page, 600)
    type_in(page, page.locator('input[data-k="KAN-4"][data-f="total"]'), '16')
    page.select_option('select[data-k="KAN-4"][data-f="shift"]', 'end')
    snap(page, 600)
    hold(page, 1200)

    click(page, page.locator('#s-stat > summary'))
    hold(page, 2000)
    scroll_to(page, 10000)
    hold(page, 1800)

    click(page, page.locator('#s-calc'))
    page.wait_for_selector('#p-box table')
    page.wait_for_timeout(500)
    hold(page, 2000)
    click(page, page.locator('[data-view="list"]'))
    hold(page, 1300)
    click(page, page.locator('[data-view="table"]'))
    hold(page, 1200)

    click(page, page.locator('#p-send'))
    for _ in range(80):
        snap(page, 120)
        if 'Sent' in page.locator('#p-send').inner_text():
            break
    hold(page, 1800)

    # 4. Review
    click(page, nav('clear'))
    hold(page, 1000)
    click(page, page.locator('#x-find'))
    page.wait_for_selector('#x-box table')
    page.wait_for_timeout(500)
    hold(page, 2000)
    cell = page.locator('[data-xcell="KAN-3|2026-10-14"]')
    click(page, cell)
    for _ in range(6):
        snap(page, 100)
    hold(page, 1500)
    click(page, cell)
    for _ in range(6):
        snap(page, 100)
    hold(page, 2000)
