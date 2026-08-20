import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.goto("http://localhost:8765")
        
        # Click the button
        print("Clicking generate button...")
        await page.click("#generatePerformanceButton")
        
        # Wait for the output block to be visible and have content
        print("Waiting for generation to finish...")
        
        # the button becomes "生成业绩摘要" again after generation finishes.
        # we can wait until button text is "生成业绩摘要" again, or wait for .performance-output-card to have text.
        await page.wait_for_selector("#generatePerformanceButton:not([disabled])", timeout=120000)
        
        # Get the text content of the output block
        output = await page.evaluate('document.querySelector("#performanceOutputBlock").innerText')
        
        with open("frontend_test_results.txt", "w") as f:
            f.write(output)
            
        print("Done. Results written to frontend_test_results.txt")
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
