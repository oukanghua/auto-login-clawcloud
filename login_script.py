# 文件名: login_script.py
import os
import time
import pyotp
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth 

def run_login():
    # 从环境变量读取配置信息
    username = os.environ.get("GH_USERNAME")
    password = os.environ.get("GH_PASSWORD")
    totp_secret = os.environ.get("GH_2FA_SECRET")

    if not username or not password:
        print("❌ 错误: 未设置账号密码环境变量。")
        return

    print("🚀 [Step 1] 访问 ClawCloud...")
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False, 
            args=["--disable-blink-features=AutomationControlled"]
        )
        context = browser.new_context(viewport={'width': 1920, 'height': 1080})
        page = context.new_page()

        Stealth().apply_stealth_sync(page)

        # 1. 访问主页
        page.goto("https://ap-northeast-1.run.claw.cloud/")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(3000)
        page.screenshot(path="01_home_page.png")
        print("📸 已截图: 01_home_page.png")

        # 2. 点击 GitHub 按钮
        print("🔍 [Step 2] 使用 JS 原生指令点击 GitHub 按钮...")
        try:
            login_button = page.locator("button.chakra-button:has-text('GitHub')")
            if login_button.count() > 0:
                login_button.first.evaluate("el => el.click()")
            page.wait_for_timeout(3000)
            page.screenshot(path="02_after_click_github.png")
            print("📸 已截图: 02_after_click_github.png")
        except Exception as e:
            print(f"⚠️ 点击异常: {e}")

        # 3. 填写 GitHub 账号密码
        print("⏳ [Step 3] 检查 GitHub 登录页...")
        try:
            page.wait_for_url(lambda url: "github.com" in url, timeout=15000)
            if "login" in page.url:
                page.fill("#login_field", username)
                page.fill("#password", password)
                page.click("input[name='commit']")
                page.wait_for_timeout(3000)
            page.screenshot(path="03_github_login.png")
            print("📸 已截图: 03_github_login.png")
        except Exception as e:
            print(f"ℹ️ 未进入账号密码填写页: {e}")

        # 4. 处理 2FA
        print("🔐 [Step 4] 检查 2FA 双重验证...")
        page.wait_for_timeout(3000)
        if "two-factor" in page.url or page.locator("#app_totp").count() > 0:
            if totp_secret:
                try:
                    token = pyotp.TOTP(totp_secret).now()
                    page.fill("#app_totp", token)
                    print(f"✅ 已填入 6 位验证码: {token}")
                    try:
                        page.locator("button:has-text('Verify')").click(timeout=3000)
                        print("✅ 已主动点击 Verify 验证按钮")
                    except:
                        pass
                    page.wait_for_timeout(4000)
                except Exception as e:
                    print(f"❌ 填入 2FA 失败: {e}")
            else:
                print("❌ 未配置 2FA 密钥！")
        page.screenshot(path="04_after_2fa.png")
        print("📸 已截图: 04_after_2fa.png")

        # 5. 处理授权页 (Authorize)
        print("⚠️ [Step 5] 检查授权请求...")
        if "authorize" in page.url.lower() or page.locator("#js-oauth-authorize-btn").count() > 0:
            try:
                auth_btn = page.locator("button[name='authorize_app'], #js-oauth-authorize-btn, button:has-text('Authorize')")
                if auth_btn.count() > 0:
                    auth_btn.first.click(timeout=5000)
                    print("✅ 已点击授权(Authorize)按钮")
                page.wait_for_timeout(4000)
            except Exception as e:
                print(f"⚠️ 点击授权按钮异常: {e}")
        page.screenshot(path="05_after_authorize.png")
        print("📸 已截图: 05_after_authorize.png")

        # 6. 等待最终跳转回控制台
        print("⏳ [Step 6] 等待最终跳转结果 (15秒)...")
        page.wait_for_timeout(15000)
        final_url = page.url
        page.screenshot(path="06_final_result.png")
        print("📸 已截图: 06_final_result.png")

        # 验证结果
        is_success = False
        if page.get_by_text("App Launchpad").count() > 0 or "console" in final_url or "private-team" in final_url:
            is_success = True
        elif "signin" not in final_url and "github.com" not in final_url:
            is_success = True

        if is_success:
            print("🎉🎉🎉 登录成功！")
        else:
            print("😭😭😭 登录失败。请检查最新截图。")
            exit(1)

        browser.close()

if __name__ == "__main__":
    run_login()
