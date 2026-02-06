# 文件名: login_script.py
# 作用: 自动登录 ClawCloud Run（终极修复版：精准处理 GitHub OAuth 流程）

import os
import time
import pyotp
import json
import re
import base64
from urllib.parse import urlparse, parse_qs
from playwright.sync_api import sync_playwright, TimeoutError

def save_debug_artifacts(page, step_name):
    """保存截图、脱敏 Cookie 和页面 HTML（含关键状态参数）"""
    try:
        # 截图
        page.screenshot(path=f"{step_name}.png", full_page=True)
        
        # 保存脱敏 Cookie
        cookies = page.context.cookies()
        safe_cookies = [
            {**c, 'value': '***REDACTED***'} if 'value' in c else c 
            for c in cookies
        ]
        with open(f"{step_name}_cookies.json", "w") as f:
            json.dump(safe_cookies, f, indent=2)
        
        # 保存页面 HTML（脱敏密码字段）
        html = page.content()
        html = re.sub(r'(<input[^>]*type=["\']password["\'][^>]*value=["\'])[^"\']*(["\'])', r'\1***REDACTED***\2', html, flags=re.IGNORECASE)
        with open(f"{step_name}_page.html", "w", encoding="utf-8") as f:
            f.write(html)
        
        print(f"🔍 调试文件已保存: {step_name}.png, _cookies.json, _page.html")
    except Exception as e:
        print(f"⚠️ 保存调试文件失败: {e}")

def is_logged_in(page):
    """检测是否已登录 ClawCloud 控制台"""
    try:
        if page.get_by_text("App Launchpad", exact=False).count() > 0:
            return True, "检测到 'App Launchpad' 文本"
        if page.get_by_text("Devbox", exact=False).count() > 0:
            return True, "检测到 'Devbox' 文本"
        if "private-team" in page.url or "/console" in page.url:
            return True, f"URL 包含控制台特征: {page.url}"
        if page.locator('[data-testid="user-menu"], .user-avatar, #user-menu').count() > 0:
            return True, "检测到用户菜单元素"
    except:
        pass
    return False, None

def find_github_button(page, max_retries=3):
    """多策略查找 GitHub 登录按钮（带重试）"""
    strategies = [
        ("get_by_role(button, GitHub)", lambda: page.get_by_role("button", name=re.compile(r"GitHub", re.IGNORECASE))),
        ("get_by_text(Sign in with GitHub)", lambda: page.get_by_text(re.compile(r"Sign in with GitHub", re.IGNORECASE))),
        ("locator(button:has-text(GitHub))", lambda: page.locator('button:has-text("GitHub"), a:has-text("GitHub")')),
        ("locator([data-testid*='github'])", lambda: page.locator('[data-testid*="github" i], [href*="github" i]')),
        ("locator(.github-btn)", lambda: page.locator('.github-btn, .btn-github, [class*="github"]')),
    ]
    
    for attempt in range(max_retries):
        print(f"🔍 尝试定位 GitHub 按钮 (第 {attempt+1}/{max_retries} 次)...")
        page.wait_for_timeout(2000)
        
        for name, locator_func in strategies:
            try:
                locator = locator_func()
                if locator.count() > 0:
                    locator.first.wait_for(state="visible", timeout=5000)
                    print(f"✅ 通过策略 '{name}' 找到 GitHub 按钮")
                    return locator.first
            except Exception:
                continue
        print(f"⚠️ 本轮尝试未找到按钮，刷新页面重试...")
        page.reload(wait_until="domcontentloaded")
    
    return None

def run_login():
    # =============== 环境变量校验 ===============
    username = os.environ.get("GH_USERNAME")
    password = os.environ.get("GH_PASSWORD")
    totp_secret = os.environ.get("GH_2FA_SECRET")
    
    if not all([username, password, totp_secret]):
        print("❌ 错误: 必须设置 GH_USERNAME, GH_PASSWORD, GH_2FA_SECRET 环境变量！")
        exit(1)
    print(f"✅ 环境变量校验通过 (用户名: {username[:3]}***)")

    # =============== 启动浏览器 ===============
    print("🚀 [Step 1] 启动浏览器（模拟真实 Chrome 环境）...")
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox"
            ]
        )
        context = browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            locale="en-US",
            timezone_id="America/Los_Angeles",
            permissions=["geolocation"],
            java_script_enabled=True,
            bypass_csp=True,
            extra_http_headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Accept-Encoding": "gzip, deflate, br",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-User": "?1",
                "Upgrade-Insecure-Requests": "1"
            }
        )
        page = context.new_page()
        
        # =============== 访问 ClawCloud + 检测登录状态 ===============
        target_url = "https://us-west-1.run.claw.cloud/"
        print(f"🌐 [Step 2] 访问目标站点: {target_url}")
        page.goto(target_url, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_load_state("networkidle", timeout=30000)
        
        logged_in, reason = is_logged_in(page)
        if logged_in:
            print(f"🎉 检测到已登录状态！原因: {reason}")
            save_debug_artifacts(page, "ALREADY_LOGGED_IN")
            print("✅ 跳过登录流程，任务成功！")
            browser.close()
            return
        
        print("ℹ️ 未检测到登录状态，继续执行登录流程...")
        save_debug_artifacts(page, "BEFORE_LOGIN")

        # =============== 智能查找 GitHub 按钮 ===============
        print("🔍 [Step 3] 智能查找 GitHub 登录按钮...")
        github_btn = find_github_button(page, max_retries=3)
        
        if not github_btn:
            print("❌ 严重错误: 尝试所有策略后仍未找到 GitHub 按钮！")
            save_debug_artifacts(page, "GITHUB_BUTTON_NOT_FOUND")
            print("\n🔍 请检查以下文件定位问题:")
            print("   - GITHUB_BUTTON_NOT_FOUND.png (页面截图)")
            print("   - GITHUB_BUTTON_NOT_FOUND_page.html (页面结构)")
            print("   - GITHUB_BUTTON_NOT_FOUND_cookies.json (会话状态)")
            exit(1)
        
        github_btn.click()
        print("✅ GitHub 按钮已点击")
        page.wait_for_timeout(1000)
        save_debug_artifacts(page, "AFTER_GITHUB_CLICK")

        # =============== GitHub 登录流程 ===============
        try:
            # 等待跳转到 GitHub
            page.wait_for_url(lambda url: "github.com" in url, timeout=25000)
            
            # 填写 GitHub 账号密码
            if "login" in page.url:
                print("🔒 填写 GitHub 账号密码...")
                page.fill("#login_field", username)
                page.fill("#password", password)
                page.click("input[name='commit']")
                print("📤 账号密码已提交")
                page.wait_for_timeout(2000)
                save_debug_artifacts(page, "GITHUB_LOGIN_SUBMITTED")
            
            # 处理 2FA 验证
            if "two-factor" in page.url or page.locator("#app_totp").count() > 0:
                print("🔐 [Step 5] 检测到 2FA 验证页面！")
                totp = pyotp.TOTP(totp_secret)
                token = totp.now()
                print(f"🔢 生成 TOTP 验证码: {token}")
                
                page.fill("#app_totp", token)
                page.keyboard.press("Enter")  # 关键：必须回车提交
                print("✅ 验证码已提交，等待授权页面...")
                page.wait_for_timeout(2000)
                save_debug_artifacts(page, "2FA_SUBMITTED")
            
            # =============== 核心修复：等待 GitHub 授权页面并处理 ===============
            print("⏳ [Step 6] 等待 GitHub 授权页面...")
            try:
                # 等待授权页面（包含 authorize）
                page.wait_for_url("*authorize*", timeout=20000)
                print(f"✅ 授权页面已加载: {page.url}")
                save_debug_artifacts(page, "GITHUB_AUTHORIZE_PAGE")
                
                # 提取 state 参数（用于验证）
                parsed = urlparse(page.url)
                query = parse_qs(parsed.query)
                authorize_state = query.get('state', [None])[0]
                print(f"   📌 授权页面 state: {authorize_state}")
                
                # 点击 Authorize 按钮
                print("⚠️ 点击 'Authorize' 按钮...")
                authorize_btn = page.get_by_role("button", name=re.compile(r"Authorize", re.IGNORECASE))
                authorize_btn.wait_for(state="visible", timeout=10000)
                authorize_btn.click()
                print("✅ Authorize 按钮已点击")
                page.wait_for_timeout(1000)
                save_debug_artifacts(page, "AUTHORIZE_CLICKED")
                
            except TimeoutError:
                print("⚠️ 未检测到授权页面（可能已自动授权）")
                # 尝试直接等待回调页面
                pass

            # =============== 核心修复：等待回调页面 + 状态验证 ===============
            print("⏳ [Step 7] 等待 ClawCloud 回调页面 (20秒)...")
            try:
                # 等待回调页面（包含 /callback）
                page.wait_for_url("**/callback**", timeout=20000)
                print(f"✅ 回调页面已加载: {page.url}")
                save_debug_artifacts(page, "CALLBACK_PAGE")
                
                # 提取回调页面的 state
                parsed = urlparse(page.url)
                query = parse_qs(parsed.query)
                callback_state = query.get('state', [None])[0]
                print(f"   📌 回调页面 state: {callback_state}")
                
                # 验证 state 是否匹配
                if authorize_state and authorize_state == callback_state:
                    print("✅ STATE 验证通过！")
                else:
                    print("❌ STATE 验证失败！授权流程可能中断")
                    page.screenshot(path="state_mismatch.png")
            except TimeoutError:
                print("⚠️ 未检测到回调页面（可能已自动跳转）")
                # 尝试直接等待控制台
                pass

            # =============== 核心修复：等待跳转到控制台（30秒） ===============
            print("⏳ [Step 8] 等待跳转回 ClawCloud 控制台 (30秒)...")
            try:
                page.wait_for_url(target_url, timeout=30000)
                print(f"✅ 成功跳转至: {page.url}")
            except TimeoutError:
                print(f"⚠️ 未在 30 秒内跳转到 {target_url}")
                print(f"   当前页面 URL: {page.url}")
                page.screenshot(path="final_redirect_fail.png")
                save_debug_artifacts(page, "FINAL_STATE")
            
            # =============== 验证登录状态 ===============
            logged_in, reason = is_logged_in(page)
            if logged_in:
                print(f"\n{'='*50}\n🎉🎉🎉 LOGIN SUCCESS! ({reason})\n{'='*50}")
                with open("login_success.txt", "w") as f:
                    f.write(f"Success at {time.ctime()}\nURL: {page.url}\nReason: {reason}")
                browser.close()
                return
            else:
                print(f"\n{'='*50}\n😭 LOGIN FAILED\n{'='*50}")
                print("🔍 请检查以下文件分析原因:")
                print("   - CALLBACK_PAGE_page.html (回调页面结构)")
                print("   - FINAL_STATE_page.html (最终页面结构)")
                print("   - state_mismatch.png (状态不匹配截图)")
                exit(1)
                
        except Exception as e:
            print(f"❌ 流程执行异常: {str(e)[:200]}")
            save_debug_artifacts(page, "ERROR_STATE")
            raise

if __name__ == "__main__":
    try:
        run_login()
    except Exception as e:
        print(f"\n❌ 脚本崩溃: {e}")
        import traceback
        traceback.print_exc()
        exit(1)
