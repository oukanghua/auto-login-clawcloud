# 文件名: login_script.py
# 作用: 自动登录 ClawCloud Run（修复版：完整处理 GitHub 2FA + 授权 + 模拟浏览器头 + Cookie 调试）

import os
import time
import pyotp
import json
import re
from playwright.sync_api import sync_playwright

def print_cookies(page, step_name):
    """打印当前页面 Cookie（脱敏敏感字段）"""
    try:
        cookies = page.context.cookies()
        safe_cookies = [
            {k: (v if k not in ['value'] else '***REDACTED***') for k, v in c.items()}
            for c in cookies
        ]
        print(f"🍪 [{step_name}] Cookie 概览 ({len(cookies)} 个):")
        for c in safe_cookies[:3]:  # 仅打印前3个脱敏信息
            print(f"   - {c.get('name', 'N/A')} | Domain: {c.get('domain', 'N/A')}")
        # 保存完整 Cookie 到文件（Actions 中可下载）
        with open(f"cookies_{step_name.replace(' ', '_').lower()}.json", "w") as f:
            json.dump(cookies, f, indent=2)
        print(f"   💾 完整 Cookie 已保存至: cookies_{step_name.replace(' ', '_').lower()}.json")
    except Exception as e:
        print(f"⚠️ [{step_name}] Cookie 打印失败: {e}")

def run_login():
    # =============== 环境变量校验 ===============
    username = os.environ.get("GH_USERNAME")
    password = os.environ.get("GH_PASSWORD")
    totp_secret = os.environ.get("GH_2FA_SECRET")
    
    if not all([username, password, totp_secret]):
        print("❌ 错误: 必须设置 GH_USERNAME, GH_PASSWORD, GH_2FA_SECRET 环境变量！")
        exit(1)
    
    print(f"✅ 环境变量校验通过 (用户名: {username[:3]}***, 2FA密钥: {totp_secret[:4]}***)")
    
    # =============== 启动浏览器（关键：设置完整浏览器请求头） ===============
    print("🚀 [Step 1] 启动浏览器（模拟真实 Chrome 环境）...")
    with sync_playwright() as p:
        # 模拟真实 Chrome 浏览器的所有关键请求头
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            locale="en-US",
            timezone_id="America/Los_Angeles",  # ClawCloud 服务器时区
            permissions=["geolocation"],  # 避免权限弹窗干扰
            java_script_enabled=True,
            bypass_csp=True  # 绕过内容安全策略（部分站点需要）
        )
        page = context.new_page()
        
        # =============== 访问 ClawCloud ===============
        target_url = "https://us-west-1.run.claw.cloud/"
        print(f"🌐 [Step 2] 访问目标站点: {target_url}")
        page.goto(target_url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_load_state("networkidle")
        print_cookies(page, "ClawCloud_Initial")

        # =============== 点击 GitHub 登录 ===============
        print("🔍 [Step 3] 寻找 GitHub 登录按钮...")
        try:
            login_button = page.get_by_role("button", name=re.compile(r"GitHub", re.IGNORECASE))
            login_button.wait_for(state="visible", timeout=15000)
            login_button.click()
            print("✅ GitHub 按钮已点击")
        except Exception as e:
            print(f"⚠️ 未找到 GitHub 按钮（可能已登录）: {e}")
            # 尝试直接验证是否已在控制台
            if "private-team" in page.url or page.get_by_text("App Launchpad").count() > 0:
                print("🎉 检测到已登录状态！跳过登录流程")
                browser.close()
                return
            else:
                page.screenshot(path="step3_fail.png")
                exit(1)

        # =============== GitHub 账号密码登录 ===============
        print("⏳ [Step 4] 等待跳转至 GitHub 登录页...")
        try:
            page.wait_for_url(lambda url: "github.com/login" in url or "github.com/session" in url, timeout=20000)
            if "login" in page.url:
                print("🔒 填写 GitHub 账号密码...")
                page.fill("#login_field", username)
                page.fill("#password", password)
                page.click("input[name='commit']")
                print("📤 账号密码已提交")
                page.screenshot(path="github_login_submitted.png")
                print_cookies(page, "GitHub_After_Login")
        except Exception as e:
            print(f"ℹ️ 跳过密码填写（可能已登录）: {e}")

        # =============== 处理 2FA 验证 ===============
        page.wait_for_timeout(2000)
        if "two-factor" in page.url or page.locator("#app_totp").count() > 0:
            print("🔐 [Step 5] 检测到 GitHub 2FA 验证页面！")
            print_cookies(page, "GitHub_2FA_Page")
            
            try:
                totp = pyotp.TOTP(totp_secret)
                token = totp.now()
                print(f"🔢 生成 TOTP 验证码: {token}")
                
                page.fill("#app_totp", token)
                page.keyboard.press("Enter")  # ⚠️ 关键：必须回车提交！
                print("✅ 验证码已提交，等待授权页面...")
                page.screenshot(path="2fa_submitted.png")
            except Exception as e:
                print(f"❌ 2FA 处理失败: {e}")
                page.screenshot(path="2fa_error.png")
                exit(1)
        else:
            print("ℹ️ 未检测到 2FA 页面（可能已跳过）")

        # =============== 处理 GitHub 授权页面（核心修复！） ===============
        print("⏳ [Step 6] 等待 GitHub 授权页面 (Authorize)...")
        try:
            # 等待授权页面加载（URL 包含 authorize）
            page.wait_for_url("*authorize*", timeout=25000)
            print("✅ 授权页面已加载！")
            print_cookies(page, "GitHub_Authorize_Page")
            page.screenshot(path="github_authorize_page.png")
            
            # 点击 Authorize 按钮
            print("⚠️ 点击 'Authorize' 按钮...")
            authorize_btn = page.get_by_role("button", name=re.compile(r"Authorize", re.IGNORECASE))
            authorize_btn.wait_for(state="visible", timeout=10000)
            authorize_btn.click()
            print("✅ Authorize 按钮已点击")
            page.screenshot(path="authorize_clicked.png")
        except Exception as e:
            # 检查是否已自动跳转（部分账号可能无授权页）
            if "claw.cloud" in page.url.lower():
                print(f"ℹ️ 已自动跳转回 ClawCloud（无授权页）: {page.url}")
            else:
                print(f"❌ 授权流程异常: {e}")
                page.screenshot(path="authorize_fail.png")
                print_cookies(page, "After_Authorize_Attempt")
                exit(1)

        # =============== 等待跳转回 ClawCloud 控制台 ===============
        print("⏳ [Step 7] 等待跳转回 ClawCloud 控制台 (最长 30 秒)...")
        try:
            page.wait_for_url(target_url, timeout=30000)
            print(f"✅ 成功跳转至: {page.url}")
        except Exception as e:
            print(f"⚠️ 未在预期时间内跳转，当前 URL: {page.url}")
            page.screenshot(path="final_redirect_fail.png")
        
        # =============== 验证登录状态 ===============
        print_cookies(page, "ClawCloud_Final")
        page.screenshot(path="login_result.png")
        print("📸 已保存最终截图: login_result.png")
        
        final_url = page.url
        print(f"📍 最终页面 URL: {final_url}")
        
        # 多重验证登录成功
        is_success = False
        if page.get_by_text("App Launchpad").count() > 0 or page.get_by_text("Devbox").count() > 0:
            is_success = True
            print("✅ 检测到控制台特征文本: 'App Launchpad' 或 'Devbox'")
        elif "private-team" in final_url or "console" in final_url:
            is_success = True
            print("✅ URL 包含控制台特征路径")
        elif "signin" not in final_url.lower() and "github.com" not in final_url.lower():
            is_success = True
            print("✅ URL 不是登录页或 GitHub 页")
        
        # =============== 结果输出 ===============
        if is_success:
            print("\n" + "="*50)
            print("🎉🎉🎉 LOGIN SUCCESS! ClawCloud 控制台已就绪！")
            print("="*50)
            # 保存成功 Cookie 供后续调试
            with open("cookies_success.json", "w") as f:
                json.dump(page.context.cookies(), f, indent=2)
            print("💾 成功状态 Cookie 已保存至: cookies_success.json")
        else:
            print("\n" + "="*50)
            print("😭😭😭 LOGIN FAILED! 请检查截图和 Cookie 文件")
            print("="*50)
            print("🔍 建议检查:")
            print("   1. GitHub 2FA 密钥是否正确 (GH_2FA_SECRET)")
            print("   2. GitHub 账号密码是否有效")
            print("   3. 查看 authorize_fail.png / final_redirect_fail.png")
            print("   4. 检查 cookies_GitHub_Authorize_Page.json 内容")
            exit(1)
        
        browser.close()

if __name__ == "__main__":
    try:
        run_login()
    except Exception as e:
        print(f"\n❌ 脚本执行异常: {e}")
        import traceback
        traceback.print_exc()
        exit(1)
