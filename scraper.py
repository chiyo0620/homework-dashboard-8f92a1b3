import os
import json
import time
from datetime import datetime, timezone
from playwright.sync_api import sync_playwright

def run():
    school_id = os.environ.get("LOILO_SCHOOL_ID")
    user_id = os.environ.get("LOILO_USER_ID")
    password = os.environ.get("LOILO_PASSWORD")

    print("🚀 スクレイパーを起動します...")
    unsubmitted_items = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            locale="ja-JP",
            timezone_id="Asia/Tokyo",
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        try:
            print("🌐 ログインページへアクセスしています...")
            page.goto("https://loilonote.app/login", wait_until="networkidle")
            time.sleep(2)

            warning = page.locator("#continue").first
            if warning.count() > 0 and warning.is_visible():
                warning.click(force=True)
                time.sleep(1)

            login_btn = page.locator("text=/ロイロノートでログイン|Sign in with LoiLoNote/i").first
            if login_btn.count() > 0 and login_btn.is_visible():
                login_btn.click(force=True)
                time.sleep(2)

            print("⏳ ログインフォームの表示を待機しています...")
            page.locator("input:not([type='hidden'])").first.wait_for(state="visible", timeout=20000)

            inputs = page.locator("input:not([type='hidden'])")
            if inputs.count() >= 3:
                inputs.nth(0).fill(school_id)
                inputs.nth(1).fill(user_id)
                inputs.nth(2).fill(password)
            else:
                page.locator("input[placeholder*='学校'], input[name='client_id']").first.fill(school_id)
                page.locator("input[placeholder*='ユーザー'], input[name='username']").first.fill(user_id)
                page.locator("input[type='password'], input[name='password']").first.fill(password)

            submit_btn = page.locator("button:has-text('ログイン'), button:has-text('Sign in'), input[type='submit']").first
            if submit_btn.count() > 0:
                submit_btn.click(force=True)

            print("送信完了。マイページへの遷移を待機しています...")
            page.wait_for_url("**/_/**", timeout=30000)
            page.wait_for_selector(".courseListBody", state="attached", timeout=20000)
            
            # 初期描画が安定するまで少し長めに待機
            page.wait_for_load_state("networkidle")
            time.sleep(2)
            print("✅ マイページが表示されました。全教科のデータ抽出を開始します。")

            courses = page.locator(".courseListBody .roundListItem.courseListItem")
            course_count = courses.count()
            print(f"📌 教科を {course_count} 件検出しました。")

            seen_task_keys = set()

            for i in range(course_count):
                try:
                    course = page.locator(".courseListBody .roundListItem.courseListItem").nth(i)
                    course.scroll_into_view_if_needed()
                    
                    subject_el = course.locator(".ellipsisText").first
                    subject_name = subject_el.inner_text().strip() if subject_el.count() > 0 else f"教科{i+1}"
                    
                    print(f"➡️ [{i+1}/{course_count}] 教科「{subject_name}」を確認中...")
                    
                    # 【改善点1】クリックが反映され、aria-selected="true" になるまで最大3回リトライ
                    for attempt in range(3):
                        course.click(force=True)
                        time.sleep(0.5)
                        is_selected = course.get_attribute("aria-selected") == "true"
                        if is_selected:
                            break
                        time.sleep(0.5)

                    # 【改善点2】提出箱タブを取得し、確実にアクティブ化（aria-selected="true"）する
                    submission_tab = page.locator('div[role="tab"][id$="-submissionBox"]').first
                    submission_tab.wait_for(state="attached", timeout=10000)
                    
                    for attempt in range(3):
                        if submission_tab.get_attribute("aria-selected") == "true":
                            break
                        submission_tab.click(force=True)
                        time.sleep(0.5)

                    # 【改善点3】セクション、または「提出箱」の中身がDOMに現れるまで動的に待機
                    try:
                        page.locator('.courseMenuBody .roundListSection, .courseMenuBody .emptyView').first.wait_for(state="attached", timeout=4000)
                    except:
                        pass

                    # レンダリング完了のための最小限のクッション
                    time.sleep(1.0)
                    
                    sections = page.locator('.courseMenuBody .roundListSection')
                    sec_count = sections.count()
                    if sec_count == 0:
                        continue

                    for s_idx in range(sec_count):
                        section = sections.nth(s_idx)
                        header_el = section.locator('.roundListSectionHeader').first
                        header_text = header_el.inner_text().strip() if header_el.count() > 0 else "期限不明"

                        items = section.locator('.roundListItem')
                        item_count = items.count()

                        for it_idx in range(item_count):
                            item = items.nth(it_idx)

                            not_submitted_badge = item.locator('.submissionStatusBadge[data-status="notSubmitted"]')
                            if not_submitted_badge.count() == 0:
                                continue

                            title_el = item.locator(".roundListItemBody .ellipsisText").first
                            title = title_el.inner_text().strip() if title_el.count() > 0 else ""
                            
                            if not title or "のノート" in title or "共有ノート" in title or "タイムライン" in title:
                                continue

                            count_down_el = item.locator(".submissionCountDownText").first
                            if count_down_el.count() > 0 and count_down_el.inner_text().strip():
                                deadline = count_down_el.inner_text().strip()
                            else:
                                deadline = header_text.replace("締切", "").strip()

                            task_key = f"{subject_name}_{title}_{deadline}"
                            if task_key not in seen_task_keys:
                                seen_task_keys.add(task_key)
                                unsubmitted_items.append({
                                    "id": f"{subject_name}_{title}",
                                    "subject": subject_name,
                                    "title": title,
                                    "deadline": deadline
                                })
                                print(f"   📥 [未提出検出] {subject_name} | {title} (締切: {deadline})")

                except Exception as ex:
                    print(f"   ⚠️ 教科「{subject_name}」の処理中にスキップ: {ex}")
                    continue

        except Exception as e:
            print(f"❌ 致命的なエラーが発生しました: {e}")
            try:
                page.screenshot(path="error_critical.png")
            except:
                pass
            raise e
        finally:
            browser.close()

    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    
    result = {
        "updated_at": now_utc,
        "count": len(unsubmitted_items),
        "items": unsubmitted_items
    }

    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
        
    print(f"🎉 処理完了。未提出タスク {len(unsubmitted_items)} 件を data.json に保存しました。")

if __name__ == "__main__":
    run()
