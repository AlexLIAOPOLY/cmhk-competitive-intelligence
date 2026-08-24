import csv
import json
import tempfile
import unittest
from pathlib import Path

from hk_competitor_product_crawl import (
    CURRENT_SOURCES,
    _apply_verification,
    _normalise_plan_row,
    _parse_page,
    _write_quality_audit,
    crawl_competitor_products,
)


THREE_TEXT = """
5G Monthly SIM Plan
Basic monthly fee is $124 with local data 30GB and 3,000 local voice minutes.
Upgrade Offers +$48/month 20GB WORLD PASS - Asia Pacific.
"""

THREE_PROMO_2024_TEXT = """
Terms and Conditions: The 30GB monthly local data of $124 monthly plan includes 15 GB basic monthly local data entitlement and 15GB monthly bonus data during contract period.
The 50GB monthly local data of $148 monthly plan includes 15GB basic monthly local data entitlement and 35GB monthly bonus local data during contract period.
The 60GB local data of $188 monthly plan includes 15GB monthly basic local data entitlement of and 45GB monthly bonus local data during contract period.
When monthly mobile data usage exceeds the fair data usage of 35GB ($124 monthly plan) / 55GB ($148 monthly plan)/ 65GB ($188 monthly plan), data service will continue, but the thereafter data access speed (upload and download) will be restricted to not more than 1Mbps.
Customers are required to subscribe to a designated SIM monthly plan, commit to a 24-month contract ($124/ $148 monthly plan) / 28-month contract ($188 monthly plan) and pay an $28 admin fee per month.
"""

THREE_ADMIN_FEE_TEXT = """
5G Monthly SIM Plan More Offers Avg. monthly fee from 1 $ 100 $124 Local data 30 GB Thereafter Infinite Data.
Applicable to port-in customers with a contract commitment of 30 months, customer can enjoy $18 waiver during the contract period and pay the balance of $10 fee per month (original price: $28/month).
Monthly 30GB (Plan$124)/ 50GB (Plan $148)/ 60GB (Plan $188) local data of designated 5G SIM Monthly Plan.
"""

THREE_ADMIN_FEE_TC_TEXT = """
5G SIM 月費計劃 平均月費低至 1 $ 100 $124 本地數據 30 GB 其後任用 高達1Mbps。
基本月費 2 $ 148 本地數據 50 GB，基本月費 3 $ 188 本地數據 60 GB，基本月費 4 $ 228 本地數據 100 GB。
升級特選 +$48/月 40GB世界PASS – 亞太 (24個月合約)。
內地及港澳共享數據增值：+$68/10GB 或 $128/20GB。攜號轉台享行政費減免，原價每月行政費$28。
"""

THREE_BUSINESS_5G_TC_TEXT = """
3Business 5G SIM月費計劃 5G SIM 月費計劃 步驟1: 揀選計劃
$124 /月 本地數據 30GB + 其後任用 上限1mbps本地數據。
3,000 本地通話分鐘 24個月 合約 30個月合約 36個月合約 立即上台
$188 /月 本地數據 60GB + 其後任用 上限1mbps本地數據。
其後本地服務及其他收費 行政費 $28/月 通話分鐘及短訊 其他自選數據增值 +$388 / 100GB 或 +$30 / 5GB。
"""

THREE_SOSIM_TC_TEXT = """
新卡$33｜至抵數據體驗
服務收費 Charge (HK$) $33 服務啟用。
香港服務（預設服務組合）首 30 日 50GB 無限數據。
$48 / 30 日其後 升級至 FUP 60GB 5,000 香港通話分鐘。
"""

THREE_WORLD_PLAN_TEXT = """
Global APAC Worldwide shared data Monthly fee Chinese Mainland and Macau voice minutes Roaming voice minutes Limited time Admin fee waiver
10GB $198 50 minutes 10 minutes Subscribe
20GB $268 50 minutes 10 minutes Subscribe
30GB $338 50 minutes 10 + 10 minutes Subscribe
50GB $368 50 minutes 10 + 10 minutes Subscribe
70GB $468 100 minutes 10 + 10 minutes Subscribe
100GB $728 200 minutes 20 + 20 minutes Subscribe
200GB $958 300 minutes 20 + 20 minutes Subscribe
"""

THREE_WORLD_PLAN_TC_TEXT = """
世界通用數據 月費 內地及澳門通話分鐘 外遊通話分鐘 限時免行政費
10GB $198 50分鐘 10分鐘 立即上台
20GB $268 50分鐘 10分鐘 立即上台
30GB $338 50分鐘 10 + 10分鐘 立即上台
50GB $368 50分鐘 10 + 10分鐘 立即上台
70GB $468 100分鐘 10 + 10分鐘 立即上台
100GB $728 200分鐘 20 + 20分鐘 立即上台
200GB $958 300分鐘 20 + 20分鐘 立即上台
"""

THREE_GREATER_CHINA_PLAN_2018_OFFICIAL_TEXT = """
3 香港推出全新「共享大中華」月費計劃，月費分為$188、$238 及$328，分別享有每月
4GB、8GB 及 12GB 數據用量，客戶可於中國內地、香港、澳門及台灣四地共用，盡享 4G
極速網絡帶來的便利。申請「共享大中華」月費計劃須簽訂 24 個月合約並繳交每月$18行政費。
"""

THREE_GREATER_CHINA_PLAN_2018_QOOAH_TEXT = """
3HK 就新推出咗「共享大中華」月費計劃，月費分為 $188、$238 及 $328，
數據量每月分別有 4GB、8GB、12GB，可以喺中國內地、香港、澳門以及台灣四地共用。
"""

THREE_WORLD_PLAN_ALT_TEXT = """
Asia Pacific shared data Monthly fee Chinese Mainland and Macau voice minutes Roaming voice minutes Limited time Admin fee waiver
10GB $158 50 minutes 10 minutes Subscribe
20GB $208 50 minutes 10 minutes Subscribe
30GB $258 50 minutes 10 + 10 minutes Subscribe
50GB $288 50 minutes 10 + 10 minutes Subscribe
70GB $388 100 minutes 10 + 10 minutes Subscribe
100GB $588 200 minutes 20 + 20 minutes Subscribe
200GB $798 300 minutes 20 + 20 minutes Subscribe
"""

THREE_OFCA_2012_ORIGINAL_TEXT = """
Tariff No. U004-011-MAY2012-N Published 03-May-12 Hutchison Telephone Company Limited.
4G LTE Smartphone SIM Plan Monthly Fee $358; Basic voice mins 3900; Intra voice mins 1600; Video mins 100; Data unlimited; Fair Usage Data: The data usage after reaching 5GB.
"""

THREE_OFCA_2012_REVISION_TEXT = """
Tariff No. U004-013-MAY2012-R Published 31-May-12 Hutchison Telephone Company Limited. Effective Date 30-May-12. Revision History U004-011-MAY2012-N.
4G LTE Smartphone SIM Plan Monthly Fee $358; Basic voice mins 3900; Intra voice mins 1600; Video mins 100; Data unlimited; Fair Usage Data: The data usage after reaching 5GB.
"""

THREE_OFCA_2014_SUPER_PLAN_TEXT = """
Tariff No. U0004-002-FEB2014-R Published on 11-Feb-14. Tariff Name 3G/4G LTE Smartphone Super Plan.
$168 1400 500 500MB $0.7 $1.5 $0.7
"""

THREE_JOLLA_2014_PRESS_TEXT = """
An attractive offer from 3 Hong Kong means customers subscribing to $168 to $598 4G LTE smartphone super plan can take advantage of a Jolla handset offer for $0.
"""

THREE_WHATSAPP_PREMIUM_2015_TEXT = """
3 Hong Kong partners with WhatsApp again to launch exclusive WhatsApp Premium Data Pack and WhatsApp Premium Roaming Pass in Hong Kong.
Local WhatsApp Premium Data Pack launches for $18 a month, including unlimited WhatsApp functionality in Hong Kong, messaging, photo and video sharing, recorded audio messages and WhatsApp Calling.
WhatsApp Premium Roaming Pass launches for a promotional price of $48 a day (normal price: $88) for hassle-free WhatsApp messaging and Calling at 151 destinations.
"""

THREE_3GAMER_2017_EN_TEXT = """
3 Hong Kong dubs December Gamer Month and launches the monthly 3Gamer SIM plan and 3Gamer membership.
New customers subscribing to the HK$218 monthly plan with a 24-month contract will get a 5GB mobile data entitlement, unlimited and speedy 3Gamer game data, unlimited data to watch videos and live 3 broadcasts via the YouTube app from 9pm to 11pm, and HK$30 to buy game items.
3 Hong Kong will also offer 3Gamer membership to existing customers. For a monthly fee of HK$48, customers can purchase a 3Gamer limited item pack and enjoy worry-free data to play designated mobile games.
"""

THREE_3GAMER_2017_TC_TEXT = """
3香港推出全新3Gamer SIM月費計劃及3Gamer會藉。新客戶只需每月$218，簽約24個月，即可享每月5GB流動數據、指定熱門手遊無限全速3Gamer遊戲數據、每晚9時至11時YouTube應用程式影片免數據及每月$30遊戲道具購物額。現有月費客戶可選用3Gamer會籍，月費只需$48，即享無限數據暢玩指定熱門手遊及購買限定道具包。
"""

THREE_HOME_ENTERTAINMENT_2016_TEXT = """
3Home Broadband launches the Home Entertainment Super Pack. The 100M Home Entertainment Super Pack has a monthly fee of $138 for 24 months and includes a Google Chromecast device, residential telephone service, unlimited HGC On Air Wi-Fi and myTV SUPER. The 1G fibre-optic Home Entertainment Super Pack has a monthly fee of $188 for 24 months.
"""

THREE_3REE_BROADBAND_2010_EN_TEXT = """
3ree Broadband launches the 100M Residential Broadband Service. The 100M Residential Broadband Service has a monthly subscription fee of only $99. New subscribers may receive six months of free 100M Broadband Service or 30 months of free Residential Telephone Line Service.
"""

THREE_3REE_BROADBAND_2010_TC_TEXT = """
3寬頻無限推出100M家居寬頻服務，月費只需$99。成功安裝服務的新客戶可獲贈首六個月100M家居寬頻服務或30個月家居電話服務。
"""

THREE_EXTRABUX_2025_TEXT = """
2025香港3HK电话卡购买、激活及充值教程（套餐内容及价格+实名登记流程）
3HK电话卡及手机套餐详情 （一）上台 1、 5G 月费计划
3HK的5G上台计划有三种套餐可选，均包含3,000分钟本地通话，数据从30GB-60GB不等，可根据自己的使用情况选择。
本地数据流量 本地通话 合约期 基本月费
30GB 3,000分钟 24/30个月 HK$124
50GB + 赠3GB内地及澳门数据 3,000分钟 24个月 HK$148
60GB + 赠1GB内地及澳门数据 3,000分钟 28个月 HK$168
图片来自于 three.com.hk ，版权属于原作者
【资费详情】 行政费：HK$28/月（携号转台免行政费）
内地及港澳共享数据增值：+ $68/10GB 或 $128/20GB
"""

THREE_THRIFTYHK_2025_TEXT = """
Best 5G Mobile Plan in Hong Kong
Provider Monthly Fee / Data Data Cost Admin Fee Local Voice Data Top-up
3HK HK$168/60GB HK$2.8 HK$28 3,000 HK$30/5GB
SmarTone HK$298/110GB HK$2.71 HK$18 Unlimited HK$50/10GB
CMHK HK$399/300GB HK$1.33 Exemption Unlimited HK$30/5GB
Note: Prices and plans are for reference only and may be updated by service providers.
"""

SMARTONE_5G_TRAVEL_110G_DETAIL_TEXT = """
planInfo {"planId":"5g_110g_30m_239_travel","planName":"5G Plan","techGeneration":"5G","fee":239,"basicData":{"value":110000},"contractMonth":{"value":30},"voiceMin":{"value":-1}}
110<span class="normal-data">GB</span> Local Data
30 <span>Month</span> Contracts
Unlimited Voice Mins
5G Plan(80GB) + rebate HK$159/month and extra local data 30GB/month within the contract period
HK$239
Administration Fee HK$18
Monthly fee HK$239 is calculated based on the original monthly fee HK$398 for 5G SIM Only Service Plan.
"""

SMARTONE_5G_LISTING_TEXT = """
SmarTone PRIORITY
5G Plan 110 GB Local Data 24 Month Contracts HK$ 299 Monthly Subscription Offer 35GB APAC Roaming Data (Total in Contract Period) + 3GB per month Chinese Mainland & Macau Data Pack HK$1,500 Handset Voucher HK$500 Accessories Voucher
5G Plan 50 GB Local Data 24 Month Contracts HK$ 179 Monthly Subscription Offer 1GB per month Chinese Mainland & Macau Data Pack HK$1,000 Handset Voucher
AI Connect (+HK$28/mth) VPN-free ChatGPT
"""

SMARTONE_5G_LISTING_TC_TEXT = """
SmarTone PRIORITY
5G計劃 110 GB 本地數據 24 個月 合約期限 HK$ 299 每月 上台優惠 35GB亞太地區漫遊數據（合約期內合共）+ 每月3GB中國內地及澳門數據組合 HK$1,500手機禮券 HK$500 配件禮券
5G計劃 50 GB 本地數據 24 個月 合約期限 HK$ 179 每月 上台優惠 每月1GB中國內地及澳門數據組合 HK$1,000手機禮券
AI Connect (+HK$28/月) 免VPN直達ChatGPT
"""

SMARTONE_SUBSCRIPTION_OFFERS_NAV_TEXT = """
SmarTone Home 5G Broadband 【Online Exclusive】Free Upgrade to Wi-Fi 7 Just $178/Month.
International Roaming. 5G Starter Pack $179/Month 50 GB Local data.
The stable 5G listing/detail pages are used for structured plan rows.
"""

SMARTONE_SUBSCRIPTION_OFFERS_PLAN_TEXT = """
Latest SmarTone 5G Offers
5G Starter Pack $ 179 / Month 50 GB Local data 24-month contract Subscription Offer
6 Months of Fees for 1 Year of Disney+ Average $41/month (Retail price: $88/month)
Northbound Weekend Getaways $ 239 / Month 110 GB Local data 24-month contract Subscription Offer
Enjoy 12 Months of Disney+ (Total value $1,056)
Best for Chinese Mainland / Macau Trips $ 299 / Month Hot Deal 110 GB Local data 24-month contract Subscription Offer
The customer can enjoy Disney+ service at the SmarTone Exclusive Price of HK$81 during the contract period.
"""

SMARTONE_HOME_5G_CURRENT_TEXT = """
SmarTone Home 5G Broadband Online Exclusive Free Upgrade to Wi-Fi 7 Just $178/Month.
The page does not disclose a contract term or data allowance in this shell-visible excerpt.
"""

SMARTONE_MONEYSMART_2026_TEXT = """
手機上台優惠2026 8大電訊商5G Plan月費計劃比較 SmarTone/csl/3HK/中移動及其他
SmarTone 5G月費計劃：$179 /50GB
5G本地數據 價錢 合約期 上台優惠 / 附屬服務
180GB HK$399/月 24個月 - 每月15GB內地及澳門數據 - 每月200分鐘內地及澳門通話
110GB HK$299/月 24個月 - 35GB亞太區漫遊數據 - 每月3GB內地及澳門數據
110GB HK$239/月 24個月 - 15GB亞太區漫遊數據 - 每月2GB內地及澳門數據
50GB HK$179/月 24個月 - 每月1GB內地及澳門數據
"""

SMARTONE_ST_PROTECT_CHI_TEXT = """
SmarTone 推出 ST Protect 為客戶提供更貼心的服務 保護手機免受安全威脅
服務 服務收費
標準計劃（無需簽約） 合約優惠（12 個月合約）
ST Protect 每月 HK$28 每月 HK$18
"""

SMARTONE_ROAMING_MULTIDAY_LINKEDIN_TEXT = """
SmarTone official LinkedIn post: SmarTone has unveiled a new 4-Day Multi-Day Roaming Data Pack
for customers to enjoy unlimited roaming data instantly upon arriving at 15 destinations in Asia Pacific for only $128.
Customers can enjoy a 20% off rebate starting from the second purchase of APAC Multi-Day Roaming Data Pack.
The average daily usage fee of two 4-Day packs with a total of 8 days is $28.8.
Customers going on long-haul travels can subscribe to a 7-Day Multi-Day Roaming Data Pack for $198,
which also covers 15 destinations in Asia Pacific. The average daily usage fee of two 7-Day packs is $25.5.
"""

SMARTONE_ROAMING_PACK_TEXT = """
APAC/ Worldwide Roaming Data Pack Long validity, full speed data Charges
Service 10GB full speed roaming data, from less than $3/day (APAC) / $6 (Worldwide) on average.
Asia Pacific China Mainland/Macau, Taiwan, Australia, Bangladesh, Cambodia, Indonesia, Japan, Malaysia, New Zealand, Philippines, Singapore, South Korea, Thailand, Vietnam
HK$ 269 / 10GB Must activate it within 1 month from the successful purchase Valid for 90 days upon activation
HK$ 38 / GB or HK$ 269 / 10 GB
Worldwide Hotspots Asia Pacific Same as above USA / Canada Europe Other
HK$ 549 / 10GB Must activate it within 1 month from the successful purchase Valid for 90 days upon activation
HK$ 68 / GB or HK$ 549 / 10 GB
Monthly fee from $99 Free 1GB/month Chinese Mainland & Macau Roaming Data
Home 5G Broadband Just $178/Month
"""

SMARTONE_ROAMING_PACK_TC_TEXT = """
亞太/環球地區漫遊數據通 特長有效期，全速數據 收費
服務 10GB 全速漫遊數據，平均每日唔使$3 (亞太區) / $6 (環球地區)
亞太區 中國內地/澳門、台灣、澳洲、孟加拉、柬埔寨、印尼、日本、馬來西亞、紐西蘭、菲律賓、新加坡、南韓、泰國、越南
HK$ 269 / 10GB 須於成功購買起計 1 個月內啟用 啟用後有效期 90 日
HK$ 38 / GB 或 HK$ 269 / 10 GB
熱門環球地區 亞太區 同上 美國/加拿大 歐洲 其他
HK$ 549 / 10GB 須於成功購買起計 1 個月內啟用 啟用後有效期 90 日
HK$ 68 / GB 或 HK$ 549 / 10 GB
4.5G服務計劃 月費低至$99 SmarTone Home 5G寬頻 月費低至$178
"""

SMARTONE_ROAMING_YAS_2023_CHI_TEXT = """
SmarTone 夥拍 YAS 微保險推出漫遊數據及旅遊保險優惠。
SmarTone 最近推出的「漫遊數據多日通」，提供 7 日及 14 日的選擇，
客戶可以平均每天收費低至$23，享無限數據。
"""

ICABLE_TEXT = """
Fibre broadband service plan monthly fee HK$88 200M broadband speed.
Fibre broadband service plan monthly fee HK$168 1000M broadband speed.
"""

ICABLE_HOME_BROADBAND_SERVICE_TC_TEXT = """
i-CABLE Service Home Broadband official page.
新登記 i-CABLE 2000M 光纖入屋，只需 $118/月。
"""

ICABLE_BROADBAND_OFFER_CURRENT_TEXT = """
有線寬頻I-CABLE | 寬頻 | 香港
服務計劃詳情
有線寬頻 公居屋/私樓價優惠
私人屋苑 1000M $88 36個月
公屋居屋 1000M $68 36個月
"""

HK01_BROADBAND_2026_TEXT = """
家居寬頻上網格價2026｜網上行 HKBN 有線 HGC 六大供應商誰最抵
撰文：鍾世傑 出版：2026-05-18 11:18 更新：2026-05-18 18:02
2026 六大電訊商 1000M 家居寬頻月費比較一覽表
想一眼看出哪家最符合預算？為大家整理了6大供應商 1000M（1G）固網家居寬頻的最低月費與優惠情報（資料只供參考、以官方最新公佈為準）
供應商 最低月費 合約期 安裝費 迎新優惠及賣點
網上行 Netvigator HK$83起 30個月 公屋 $480 私樓 $680 海外連線最穩、打機最快無限制
香港寬頻 HKBN HK$88起 24個月 免安裝費 本地網速穩定、短合約期抵玩
HGC寬頻 HK$109起 24/36個月 公屋安裝費 私樓 $180 網絡質素持續改善、中規中矩
數碼通 SmarTone HK$88起 36個月 免安裝費 可選即插即用5G寬頻或光纖
有線寬頻 i-CABLE HK$88起 36個月 HK$300 指定情況可獲月費回贈抵消安裝
中國移動 CMHK HK$78起 36個月 免安裝費 公私樓劃一價錢
日本福岡旅遊SIM卡實測2026
"""

HKBN_5G_HOME_BROADBAND_TERMS_TEXT = """
HKBN_5G Home Broadband Plan_T&C_ENG_202305
Terms and conditions of the HK$118 5G Home Broadband Service Plan ("5G Home Broadband Service Plan")
Subscriber must commit to the 5G Home Broadband Service Plan for 24 months ("Minimum Commitment Period").
The special monthly fee for the 5G Home Broadband Service Plan is HK$118, with an additional monthly administration fee of HK$18.
Subscriber can only enjoy unlimited local data at one designated registered service address with designated router/device.
When local data usage reaches the 300GB local data entitlement limit in monthly bill cycle, local data service will continue
with the maximum data download speed of 5G network but subject to the Fair Usage Policy (C).
The 5G Home Broadband Service Plan does not provide local voice, roaming voice, roaming data and IDD services.
The network is supported by 3HK.
"""

HKBN_5G_HOME_BROADBAND_TERMS_202405_TEXT = """
HKBN_5G Home Broadband Plan_T&C_ENG_202405
Terms and conditions of the HK$118 5G Home Broadband Service Plan ("5G Home Broadband Service Plan")
Subscriber must commit to the 5G Home Broadband Service Plan for 24 months ("Minimum Commitment Period").
The special monthly fee for the 5G Home Broadband Service Plan is HK$118.
Subscribers can enjoy the $28 monthly administration fee waiver.
Subscriber can only enjoy unlimited local data at one designated registered service address with designated router/device.
When local data usage reaches the 300GB local data entitlement limit in monthly bill cycle, local data service will continue
with the maximum data download speed of 5G network but subject to the Fair Usage Policy (C).
The 5G Home Broadband Service Plan does not provide local voice, roaming voice, roaming data and IDD services.
The network is supported by 3HK.
"""

HKBN_5G_HOME_BROADBAND_CURRENT_TEXT = """
5G Home Broadband Monthly Plan.
5G Home Broadband Plan HK$118/month.
Unlimited 5G Broadband Data (300GB/mth + FUP).
24-months contract.
Enjoy the $28 monthly administration fee waiver.
The network is supported by 3HK.
"""

HGC_CURRENT_FIBRE_TEXT = """
Home Broadband Monthly Service Plan Basic Monthly Fee
Broadband Service Plan Standard Monthly Fee
10G $1,299 2.5G $766 2.2G $666 2G $666 1G $598 500M $488
300M $398 200M $348 100M $298 30M $198 10M $188 6M $188
Service Charges FTTH Service Non FTTH Service
Installation Charge $1,500 $680
Inspection Fee $150 $150
Relocation Charge (Internal) $1,500 $680
Order Cancellation Fee $500 $500
Monthly Billing by Mail $10 $10
Home Connectivity Consultancy Service $200 Additional Device Consultancy Service $50 / Device
"""

HGC_CURRENT_FIBRE_TC_TEXT = """
家居寬頻月費計劃 基本月費
寬頻服務計劃 正價月費
10G $1,299 2.5G $766 2.2G $666 2G $666 1G $598 500M $488
300M $398 200M $348 100M $298 30M $198 10M $188 6M $188
"""

HGC_FINDPLANKING_2026_TEXT = """
Find Plan King 版權所有 © 2026
HGC 已認證 7月6 HGC 月費$75 1000M 更新日期： 05.07.2026
簡介 三天限量 公屋 居屋 1000M $75 2500M $139 送WiFi7 Router
公屋/居屋: 1000M光纖入屋 實際月費: $89 合約期：36個月
特選公屋 $119 2000M光纖入屋
公屋/居屋: 1000M+Router+家居電話 實際月費: $109 合約期：39個月
指定私人屋苑：1000M 實際月費: $99 合約期：36個月
轉台特別組合計劃 $129 2000M光纖入屋
2.2G一家四口寬頻計劃 4組獨立ip $129
"""

HGC_BROADBAND_QUOTE_2026_TEXT = """
HGC 最新優惠 - 電訊萬事屋
特選地區客戶優惠計劃
100m低至$69起
500m低至$79起
2000m低至$119起
2200m低至$129起
優惠受安裝地址而有所不同，此為新安裝或指定寛頻用户轉台優惠。
資料只供參考，實際收費及優惠由供應商合約內容為準。
Tags : 1000M , 2026年寬頻比較 , 2500M , hgc
"""

HGC_PRICEQUOTE_2500M_CATEGORY_2025_TEXT = """
HGC/環電寬頻
5月4日 HGC環電 全新 2500M 光纖寬頻計劃詳解｜36個月合約$139／24個月合約$159｜配備Wi-Fi 7技術免安裝費
HGC環電全新2500M光纖寬頻計劃詳解，月費$139起, 36個月合約, 配Wi-Fi 7路由器免安裝費。
"""

HGC_PRICEQUOTE_2000M_X50POE_2025_TEXT = """
【HGC環電2000M連升級路由器x2裝置】月費只須﹩１５９
HGC環電推出優惠，讓您以超值價格享受 2000MB光纖入屋寬頻。
私樓月費計劃：36個月合約：月費只需$169 24個月合約：月費為$199
公居月費計劃：36個月合約：月費只需$159 24個月合約：月費為$189
"""

ICABLE_SERVICE_CHARGE_TEXT = """
Updated as of 25/10/2023 Additional Service Charge (Residential subscriber only)
i-CABLE Broadband & HomeLine Service Rates
Service Plan Regular Rate HK$
100M per month 499
200M per month 499
500M per month 529
1000M per month 569
2x1000M per month 669
Smart Broadband per month 198
Digital HomeLine Service per month 199
OTT & Additional Service Rates
Service Plan Regular Rate HK$
JOOX per month 79
"""

ICABLE_MYTV_BUNDLE_2021_TEXT = """
myTV SUPER × i-CABLE 1G Home Broadband + myTV Gold + Concurrent Viewing on 3 Devices = $198/mth Triple Up The Joy
(23 April 2021)
i-CABLE + myTV Gold Service Plan (Concurrent Viewing on 3 Devices)
i-CABLE myTV SUPER Monthly Fee*
1000 Mbps myTV Gold service myTV SUPER set-top-box + Concurrent Viewing on 2 extra devices
$198 # up
The promotion plan is for 24 months and applicable to designated broadband coverage buildings.
"""

ICABLE_MYTV_SERVICE_FEE_2021_TEXT = """
You are New Subscriber of i-CABLE / Existing i-CABLE Subscriber.
i-CABLE New Subscriber Monthly Service Plan* Service Details
1G Home Broadband + myTV Gold Service Monthly Fee* $198 Contract Period 24 months.
The above service plans are applicable to designated broadband coverage buildings.
Monthly fee is suggested retail price only, details please refer to Internet Service Provider.
"""

ICABLE_FINDPLANKING_2026_PUBLIC_HOUSING_75_TEXT = """
I-Cable $68 1000m光纖計劃 快靚正
指定地址計劃【所有計劃、免安裝費】＄48 / 1000M【4年】
公屋/居屋客戶
1️⃣＄68 / 1000M
2️⃣＄75 / 1000M / 連 路由器
3️⃣＄88 / 1000M / 家居電話
4️⃣＄108 / 1000M / 連 路由器 / 家居電話
＄98 / 1000M / 連 TP LINK Deco M4 Mesh
＄99 / 1000M / 連 5G 5GB手提計劃
＄109 / 1000M / 連 5G 10GB手提計劃
免安裝費 免1次搬遷費
私人屋苑客戶 ＄88 / 1000M / 連 路由器
"""

ICABLE_SERVICE_WIFI_2026_TEXT = """
i-CABLE Service Wi-Fi page public excerpt verified 2026-07-07.
有線寬頻 i-CABLE Wi-Fi 寬頻服務：1000M 光纖寬頻連 Wi-Fi 6 路由器，月費 $93/month，36 months contract.
"""

ICABLE_TELCOQUO_1000M_89_2026_TEXT = """
Telcoquo public search/index excerpt verified 2026-07-07.
有線寬頻i-Cable 有線寬頻家居上網4：網絡供應商 有線寬頻i-Cable；網絡 光纎寬頻；速度 1000M；種類 住宅寬頻上網(及WIFI)；月費 $89.
Use only as public third-party indexed offer reference, not as official standard price.
"""

ICABLE_TELCOQUO_1000M_118_2026_TEXT = """
Telcoquo residential broadband public index excerpt verified 2026-07-07 via public search/open result.
住宅寬頻報價分享 - Telcoquo 上網轉台報價: 有線寬頻i-Cable 私人屋苑家居上網寬頻計劃 $118 1000M.
Use only as public third-party indexed offer reference, not as official standard price.
"""

ICABLE_BROADBAND_PRICEQUOTE_1000M_68_2023_TEXT = """
Broadband-PriceQuote public i-CABLE article excerpt verified 2026-07-08.
Article date 2023年12月1日.
〖有線寬頻1000M〗公居屋月費 $68；私樓月費 $88.
對於公居屋的住戶，只需每月$68，及簽36個月合約，您就可以享受到有線寬頻的1000MB寬頻服務。
私人住戶 1000MB 寬頻月費 $88，36個月合約，免費提供 WiFi Router。
本網站分享的服務計劃內容僅能供參考，實際收費及優惠由供應商決定。
"""

ICABLE_BROADBANDQUEEN_2024_TEXT = """
i-Cable Broadband Offers | BroadbandQueen
i-Cable Broadband Offers 10 November 2024 BroadbandQueen
i-Cable Broadband offers fibre plans from 100M to 1000M.
100M monthly fee starts from $78, 500M starts from $128, and 1000M starts from $168.
The price is considered mid-range to cheap in the market.
"""

ICABLE_FINDPLANKING_2022_TEXT = """
Find Plan King 版權所有 © 2026
有線寬頻 已認證 有線寬頻光纖入屋 1000m$73 指定公居屋 更新日期： 17.03.2022
簡介 最平寬頻200m$58起-1000m $78 $106 起200/1000m+mytv super/gold
公屋/居屋： $58 200mb上網（特選屋苑）
$73 200mb連家居電話📞(特選屋苑)
$73 1000m （指定地區公居屋）
$78 1000mb 上網（公屋）
$88 1000mb 加電話
私樓： $99 200mb
$109 1000mb 獨享光纖入屋
一屋兩線200m x2 $126起
$158 1000m x2條 光纖
"""

ICABLE_KENNECHU_2020_TEXT = """
2020 家居寬頻服務比較
HGC 和記 網速：1000M 月費：HK$148 簽約：36 個月
PCCW 網上行 netvigator 網速：1000M 月費：HK$198 簽約：36 個月
Smartone 數碼通 網速：1000M 月費：HK$118 簽約：36 個月
有線寬頻 i-Cable 網速：1000M 月費：HK$98 簽約：36 個月
最後就是傳聞中，好難「cut」的 有線寬頻 月費最低更只是 HK$98。
"""

ICABLE_HKEPC_2019_TEXT = """
Icable 1000mbps $98加電視有冇伏? - 網絡寬頻 - 電腦領域 HKEPC Hardware
發表於 2019-2-13 02:31
我有時行街都見到有線做promotion sell HK$98 1000M光纖入屋。
"""

HKBN_HKEPC_2016_RENEWAL_TEXT = """
HKBN 續約價錢 - 網絡寬頻 - 電腦領域 HKEPC Hardware
發表於 2016-6-6 16:15
我10月到期，想攞左sim所以打去cs問續約，佢開1000M $248X24,$1000 coupon, 12個月sim via HKEPC Reader for Android
HKBN: A. 新約/續約：續約 B. 合約期：24個月 C. 生效明：2016年7月 D. 服務包括：100M 寬頻上網、HKBN Wi-Fi
"""

ICABLE_DISCUSS_2017_TEXT = """
有線寬頻 200M 寬頻 $88 個月抵唔抵用? - 香港討論區 discuss.com.hk.
發表於 2017-3-6. 如題，有線寬頻 200M 寬頻 $88 個月抵唔抵用?
"""

ICABLE_APPLEDAILY_2017_TEXT = """
果靈聞庫 2017-07-07 家居寬頻比較 網上行有12個月free之選.
有線家居寬頻：1000M，月費約140.7元；市場比較顯示有線 1000M 平均月費低至 HK$140.7。
"""

ICABLE_BROADBAND_PRO_2018_TEXT = """
轉介優惠: 有線寬頻 住宅寬頻 $88 200M上網
服務價錢: $88月費
服務計劃內容: 200M
服務供應商: 有線寬頻
合約期: 30 個月
安裝日期: 27/10/2018
合約日期: 14/09/2018
"""

ICABLE_BROADBAND_PRO_2017_200M_144_TEXT = """
轉介優惠: 有線寬頻 200M 上網 $116(平均價）
安裝地址: 東涌 昇薈 5座
合約日期: 04/06/2017
安裝日期: 17/06/2017
服務供應商: 有線寬頻
合約期: 36 個月
服務計劃內容: 200M
服務價錢: $144月費 （平均價116)
"""

ICABLE_BROADBAND_PRO_2016_TEXT = """
轉介優惠: 有線寬頻 送$300現金卷
服務價錢: 平均月費$144
服務計劃內容: 200M
服務供應商: 有線寬頻
合約期: 30個月
安裝日期: 15/01/2016
合約日期: 10/01/2016
"""

HKBN_BROADBAND_PRO_2017_TEXT = """
轉介優惠: 香港寬頻 HKBN 送 TVB BOX ，1000M Router ，家居電話24個月＋室內無線系統一套
安裝費：$380
服務價錢: $248月費
服務計劃內容: 1000M
服務供應商: 香港寬頻
合約期: 24 個月
安裝日期: 24/01/2017
合約日期: 21/01/2017
"""

HGC_BROADBAND_PRO_2017_TEXT = """
轉介優惠:和記寬頻HGC 1000M 送MyTV super包家居電話
安裝地址: 海麗村 海瑞樓
合約日期: 18/01/2017
安裝日期: 22/01/2017
服務供應商: 網上行 合約期: 33 個月
服務計劃內容: 1000M
服務價錢: $137月費
寬頻覆蓋：網上行(PCCW) 和記寬頻HGC 香港寬頻
"""

HKBN_PAY_TV_BUNDLE_2019_TEXT = """
HKBN Launches Mind-blowing Offer to All Pay TV Customers
HONG KONG, CHINA - Media OutReach - 9 May 2019 - HKBN Group announced today the launch of a fabulous special offer for new customers who subscribe to HKBN home broadband services and myTV Gold bundle.
This sensational package deal includes myTV Gold plus 100M home broadband services priced as low as HK$198 up per month and myTV Gold and 1000M home broadband service bundle offer for just HK$238 up per month.
New service subscribers to HKBN Enterprise Solutions and WTT can also enjoy 100M business broadband service along with myTV SUPER Basic Pack B plus the beIN SPORTS pack for just HK$588 per month.
"""

HKBN_MOMAX_2020_TEXT = """
MOMAX x HKBN Smart Home Living.
MOMAX Smart IoT Bundle includes smart home devices and monthly fee HK$88 for 24 months.
MOMAX Trio-Cleanse IoT UV-C Vacuum Robot monthly fee HK$68 for 24 months.
"""

HKBN_MOBILE_LAUNCH_2016_TEXT = """
HKBN Launches All-new Mobiles Services.
Basic monthly plans range in price from $88 up to $446.
By choosing any quad-play service bundle, customers can enjoy a further tariff discount of about 30%, and a waiver of the $18 monthly administrative fee.
For customers who port-over their existing mobile number to HKBN and opt for the $108 3GB data plan, a 2GB extra data will be offered free of charge.
HKBN Mobile Services Plans [1] S M L XL ∞
Monthly fee [2] $88 $108 $198 $248 $446
Local data network <384kbps <21Mbps 4G 4G 4G
Local data usage Unlimited [3] 3GB + 2GB (extra data for mobile number port-in) 3GB 6GB Unlimited [3]
Local voice (mins) 2,000 3,000 3,000 3,000 3,000
Customer must commit to a 24-month contract with credit card payment. Admin fee of $18 per month will be levied throughout the contract period.
Quad-play free-to-go bundle plan Monthly fee $248 up with 3GB + 2GB mobile services and $18 monthly administration fee waived.
"""

HKBN_4G_MOBILE_BUNDLE_2018_CHI_TEXT = """
香港寬頻推出 4G 「$78/月」流動通訊服務組合
HKBN Mobile Services Bundles#
Special monthly fee $78 $148 $218
Local data usage 5GB 6GB 12GB
Network 4G Maximum local download speed 21Mbps
月費組合需繳付每月 $18 行政費。
"""

HKBN_TRAVEL_POCKET_WIFI_2018_HTML_TEXT = """
HKBN announces the launch of HKBN Travel Pocket Wi-Fi for customers going on long-haul travels.
If more than the 5-day free service is reserved, each additional day will be charged at $28/day.
When daily data usage reaches 500MB, maximum upload and download speed for thereafter data access is 128kbps.
"""

HKBN_68_10GB_2022_MOBILEMAGAZINE_TEXT = """
香港寬頻 HKBN 推出 10GB 5G 計劃，每月 HK$68，數據用量達 10GB 後速度為 5Mbps。
新計劃免 HK$18 行政費，適合低用量 5G 用戶。
"""

HKBN_4G_MOBILE_BUNDLE_2017_TEXT = """
HKBN Announces All-new Disruptive 4G Mobile Services Bundle
Switch over to Enjoy 5GB Mobile Data at Only HK$78/m (Network Partner: SmarTone)
Priced at a disruptive monthly fee of only HK$78, HKBN's all-new mobile services bundle provides 4G (21Mbps) mobile experience.
Customers switching to HKBN will be entitled to 5GB data per month.
"""

HKBN_WIFI_CONCIERGE_2017_TEXT = """
HKBN Launches All-new Home Telephone and Wi-Fi Concierge Service.
For a monthly fee of only $88, customers can enjoy a hassle-free one-stop service that offers Home Telephone,
Wi-Fi Concierge 1Gbps router, 24/7 Wi-Fi technical support, VTech DECT telephone and myTV SUPER Alpha Pack.
Customers must subscribe to a 24-month service plan; customers subscribing to designated mobile services can enjoy
five months waiver over a 27-month service plan.
香港寬頻推出全新家居電話及 Wi-Fi 管家服務，月費只需$88。
"""

HKBN_MOBILE_TRIAL_2016_TEXT = """
Subscriber must register and successfully install the dedicated broadband bundle on or before 31 August 2016 to enjoy the first six-month monthly fee waiver of the $108 mobile service plan.
After the first six-month monthly fee waiver period ends, this plan will switch to a free-to-go plan, where a monthly fee of $108 plus an administration fee of $18 will be charged.
The maximum download speed for the first 3GB (or first 5GB for port-in numbers) of this mobile service plan is 21Mbps.
Local SMS Inter $0.6 each.
"""

HKBN_ENTERPRISE_MOBILE_5G_TEXT = """
Business 5G Mobile Services
With our 5G Mobile Service plan starting as low as HK$78/month*, enjoy an outstanding 5G mobile experience with blazing-fast speeds and ultra-low latency.
"""

HKBN_ENTERPRISE_MOBILE_5G_TC_TEXT = """
商業5G流動通訊服務
月費低至HK$78* ，即可盡享5G超高速、低時延的極致網絡體驗，隨時隨地連繫世界，拓展業務。
"""

HKBN_ENTERPRISE_MOBILE_4G_TEXT = """
Local Service Plans
Special Monthly Fee: $98 Standard Monthly Fee: $118 Network up to 42Mbps 5GB Local Data # 2,000 Local Voice Call Minutes * Administration Fee: $18 (waived during contract period) Contract Period: 24 Months.
Voice thereafter charges: $0.3 /minute
Special Monthly Fee: $118 Standard Monthly Fee: $138 4G Network 3GB Local Data # 3,000 Local Voice Call Minutes * Administration Fee: $18 (waived during contract period) Contract Period: 24 Months.
Special Monthly Fee: $148 Standard Monthly Fee: $168 4G Network 6GB Local Data # 3,500 Local Voice Call Minutes * Administration Fee: $18 (waived during contract period) Contract Period: 24 Months.
Special Monthly Fee: $178 Standard Monthly Fee: $198 4G Network 8GB Local Data # 4,000 Local Voice Call Minutes * Administration Fee: $18 (waived during contract period) Contract Period: 24 Months.
Greater China 4G Service Plans
Special Monthly Fee: $198 Standard Monthly Fee: $238 1GB Data For access in Hong Kong, China, Macau and Taiwan Unlimited Local Airtime Extra Data Usage: $30/0.5GB Data Usage Sharing^ Administration Fee: $18 (waived during contract period) Contract Period: 24 Months.
Special Monthly Fee: $258 Standard Monthly Fee: $298 3GB Data For access in Hong Kong, China, Macau and Taiwan Unlimited Local Airtime Extra Data Usage: $30/0.5GB Data Usage Sharing^ Administration Fee: $18 (waived during contract period) Contract Period: 24 Months.
Special Monthly Fee: $318 Standard Monthly Fee: $358 6GB Data For access in Hong Kong, China, Macau and Taiwan Unlimited Local Airtime Extra Data Usage: $20/0.5GB Data Usage Sharing^ Administration Fee: $18 (waived during contract period) Contract Period: 24 Months.
Special Monthly Fee: $448 Standard Monthly Fee: $488 10GB Data For access in Hong Kong, China, Macau and Taiwan Unlimited Local Airtime Extra Data Usage: $20/0.5GB Data Usage Sharing^ Administration Fee: $18 (waived during contract period) Contract Period: 24 Months.
"""

HKBN_ENTERPRISE_MOBILE_4G_TC_TEXT = """
本地服務計劃
優惠月費： $98 標準月費：$118 網絡最高達至42Mbps 5GB本地數據 # 2,000 本地通話分鐘 * 行政費： $18 (合約期內豁免) 合約期： 24 月
優惠月費： $118 標準月費：$138 4G網絡 3GB本地數據 # 3,000 本地通話分鐘 * 行政費：$18 (合約期內豁免) 合約期：24 月
優惠月費： $148 標準月費：$168 4G網絡 6GB本地數據 # 3,500 本地通話分鐘 * 行政費：$18 (合約期內豁免) 合約期：24 月
優惠月費： $178 標準月費：$198 4G網絡 8GB本地數據 # 4,000 本地通話分鐘 * 行政費：$18 (合約期內豁免) 合約期：24 月
大中華區4G服務計劃
優惠月費： $198 標準月費：$238 1GB數據 包括中港澳台 無限本地通話分鐘 額外數據用量：$30/0.5GB 行政費：$18 (合約期內豁免) 合約期：24 月
優惠月費： $258 標準月費：$298 3GB數據 包括中港澳台 無限本地通話分鐘 額外數據用量：$30/0.5GB 行政費：$18 (合約期內豁免) 合約期：24 月
優惠月費： $318 標準月費：$358 6GB數據 包括中港澳台 無限本地通話分鐘 額外數據用量：$20/0.5GB 行政費：$18 (合約期內豁免) 合約期：24 月
優惠月費： $448 標準月費：$488 10GB數據 包括中港澳台 無限本地通話分鐘 額外數據用量：$20/0.5GB 行政費：$18 (合約期內豁免) 合約期：24 月
"""

HKBN_OEXBN_RENDERED_TEXT = """
Home Broadband Service Offer | Hot Picks | HKBN.
HKBN 1000M Home Broadband Plan with 36-mth Home Telephone: plan price $129, average fee $129, contract 36 months.
HKBN 2.5Gbps GigaFast Broadband Plan with 24-mth Home Telephone Service: plan price $149, average fee $149, contract 24 months.
HKBN 1000M Home Broadband Plan: plan price $109, average fee $109, contract 36 months.
HKBN 2000M GigaFast Broadband Plan (Must Add on 24-mth designated Router): plan price $378, average fee $378, contract 24 months.
HKBN 1000M Home Broadband Plan: plan price $378, average fee $302.4, contract 30 months.
HKBN 1000M Home Broadband Plan: plan price $378, average fee $336, contract 27 months.
"""

HKBN_N_MOBILE_2023_TC_TEXT = """
N mobile以「N個選擇、N種生活」為理念，為用戶帶來「N個優惠」。
計劃亮點包括：月費低至$108，即可盡享本地及/或大灣區流動通訊。
成功申請更可免合約期內每月$18行政費。
Global Talk+ 漫遊通話服務及 Global SIM 旅遊數據卡亦包括在計劃亮點中。
"""

HKBN_HIGH_USAGE_MOBILE_2017_TEXT = """
Disruptively priced at $218/month for 12GB Data and myTV SUPER App.
Hong Kong Broadband Network Limited ("HKBN") today announces the launch of all-new high-usage mobile service bundles.
For as low as $218 per month, the bundles offer 12GB local data on 4.5G network and myTV SUPER app.
"""

HGC_MYTV_BUNDLE_2021_TEXT = """
Immediate Release myTV SUPER × HGC Broadband 1G Home Broadband + myTV Gold + Concurrent Viewing on 3 Devices = $198#/mth Triple Up The Joy (26 April 2021)
HGC Broadband + myTV Gold Service Plan (Concurrent Viewing on 3 Devices)
HGC Broadband myTV SUPER Monthly Fee*
1G myTV Gold service myTV SUPER set-top-box + Concurrent Viewing on 2 extra devices $198#up
The promotion plan is for 24 months and applicable to designated broadband coverage buildings.
"""

HGC_MYTV_PRICEQUOTE_2025_TEXT = """
【HGC光纎寛頻連MYTV GOLD】月費﹩１９８/【MYTV SUPER基本版】月費﹩１０９
2025年3月2日
HGC光纖寬頻推出兩款優惠方案，第一個方案是光纖寬頻搭配MYTV GOLD服務，月費$198，合約期為24個月。
第二個方案為公屋和私樓住戶提供優惠，分別是月費$109和$119，合約期為36個月，並包含24個月的MYTV SUPER基本版服務。
HGC光纖寬頻連MYTV GOLD 月費：$198 24個月合約 包含24個月的MYTV GOLD服務
HGC光纖寬頻連MYTV SUPER基本版 公屋月費：$109 / 私樓月費：$119 36個月合約 包含24個月的MYTV SUPER基本版
(資料只供參考，實際收費及優惠由供應商合約內容為準)
"""

HGC_MYTV_PRICEQUOTE_POST_2025_TEXT = """
【HGC光纎寛頻連MYTV GOLD】月費﹩１９８/【MYTV SUPER基本版】月費﹩１０９
HGC光纖寬頻推出兩款優惠方案，第一個方案是光纖寬頻搭配MYTV GOLD服務，月費$198，合約期為24個月。
第二個方案為公屋和私樓住戶提供優惠，分別是月費$109和$119，合約期為36個月，並包含24個月的MYTV SUPER基本版服務。
"""

HGC_MYTV_SERVICE_FEE_2025_TEXT = """
服務收費 - HGC 寬頻
HGC寬頻新客戶 新客戶透過HGC寬頻配合hgc on air 屋外Wi-Fi服務隨時享受 myTV SUPER 全新視聽娛樂。
寬頻娛樂組合月費計劃* 家居寬頻 1G家居寬頻 1G家居寬頻 + 家居電話 100M家居寬頻 + 家居電話
連 myTV Gold 組合 解碼器 + 2個裝置同時睇 myTV SUPER 基本版 + 1個裝置同時睇
月費* $198 $179 $139 最少申用期 24個月 24個月 24個月
上述之月費為建議零售價，詳情以網絡供應商之公佈為準。
"""

HGC_EZONE_2019_TEXT = """
目前 HGC、HKBN 和 Netvigator 三間 ISP，均有提供 2Gbps 家用寬頻服務。
HGC 寬頻 四線 2.2Gbps 服務
服務計劃（上／下傳速度）：「一家四口」2.2Gbps 光纖寬頻服務（1,000M / 2,200M） 合約期：30 個月 安裝費：免安裝費 平均服務月費＊：$218 其他優惠：(a) (b) (c)
服務計劃（上／下傳速度）：1Gbps 極速光纖寬頻服務（1,000M / 1,000M） 合約期：36 個月 安裝費：免安裝費 平均服務月費＊：$148 其他優惠：(d) (e)
(c) 每月加 $58 可享「Wi-Fi 360」屋內 Wi-Fi 服務
Netvigator 2 x 1000M 多連接寬頻服務 平均服務月費＊：$318
"""

HGC_LINE_FOR_FOUR_2018_TC_TEXT = """
HGC 寬頻推出全新「一家四口」2.2G 光纖寬頻服務及「Wi-Fi 360」服務
「一家四口」2.2G 光纖寬頻服務連 myTV SUPER 服務組合，月費$218 起，優惠期内，加送 6 個月服務。
「Wi-Fi 360」服務，月費$58 起。
"""

HGC_2G_2023_TEXT = """
HGC launches affordable 2G/2000Mbps high-speed broadband service plans.
Customers who apply on or before 31 December 2023 can enjoy a 2G/2000Mbps broadband service plan with
a Wi-Fi 6 Router at an affordable monthly fee of HK$139 per month.
"""

HGC_ON_AIR_PLAN_EN_TEXT = """
Select hgc on air Wi-Fi Day Pass
The Service offers Monthly Plan and Day Pass Plan. The HGC Broadband Service subscribers can subscribe both of the Service Plans,
but non-HGC Broadband Service subscribers are only allowed to subscribe Day Pass Service Plan.
Part of the Monthly Plan offers with contract or promotion period. HGC Broadband Service subscribers $58 monthly fee will be
automatically provided the Service and charged to HGC Broadband account after the expiry of the free / special offer period.
"""

HGC_ON_AIR_PLAN_TC_TEXT = """
選擇hgc on air Wi-Fi通行證
該服務設有月費計劃及日費計劃。HGC寬頻客戶兩種計劃均可申請，而非HGC寬頻客戶只可申請日費計劃。
部份月費計劃設有合約或優惠期。HGC寬頻客戶於試用期 / 優惠期屆滿後，該服務將自動繼續提供，
並按正價月費計劃以月費港幣$58元收取，於客戶之登記帳戶內扣除。
"""

HGC_SMART_HOME_LIVING_2020_TEXT = """
[For immediate release] HGC Broadband launches “Smart Home Living” offer for building your ideal smart home
Hong Kong, 23 October 2020 – HGC Broadband announced today the launch of its “Smart Home Living” offer.
1G home broadband plan with smart home kit
Starting from today, new customers who switched from designated home broadband service providers can select a designated 1G home broadband plan with a smart home kit and installation, starting at $119/month*.
The package includes a home security camera (1080P), window and door sensors, a control hub and a Wi-Fi router.
"""

HGC_SUPER_FUN_2016_TEXT = """
「全家 Super Fun」娛樂組合月費$138 起 睇盡「myTV SUPER」30 條主題頻道及 Disney 點播組合
香港，2016 年 3 月 14 日，3 家居寬頻推出「全家 Super Fun」娛樂組合。
客戶只需以$138的月費，即可享用 100M 家居寬頻、家居電話服務、無限「HGC on air」Wi-Fi 服務。
另有1G「全家 Super Fun」娛樂組合，超值月費只需$188。
"""

HGC_SUPER_FUN_2016_EN_TEXT = """
For Immediate Release 3 Home Broadband launches the Home Entertainment Super Pack for a monthly fee starting at just $138.
Package includes myTV SUPER and Disney SVOD channels.
Customers can watch programmes via 100M or 1G fibre broadband service for discounted monthly fees of $138 and $188 respectively.
"""

HGC_MOBILE_LAUNCH_2026_TEXT = """
HGC announces the launch of HGC Mobile expanding mobile connectivity footprint with enhanced Network-on-the-Go experience.
The plan includes 30GB of 5G local data per month, plus unlimited local data usage across 15 social and OTT entertainment applications such as YouTube, Netflix, Disney+, Apple TV, hmvod, myTV SUPER, Facebook, Instagram, WhatsApp and more.
Available at HK$98 per month, the plan allows users to enjoy high-speed mobile internet anytime, anywhere.
An additional 4GB of Chinese mainland-Macau shared data will be complemented.
Seamless One-Stop Home Broadband + Mobile Services.
For new customers, a welcome offer "One-Stop Home Broadband + Mobile Service" bundle is available starting from HK$285 per month, which includes 1000M home fibre broadband with voice service, HGCmore e-coupons and two HGC Mobile services.
"""

SMARTONE_HOME_5G_EZONE_2020_TEXT = """
SmarTone 5G 家居寬頻＄148 有得玩 市區＋村屋實測 | 15-09-2020.
SmarTone 正式公布，月費更由 HK$238 調低至 HK$148。
HK$148 月費 5G 家居寬頻 適合全港 SmarTone 5G 覆蓋住宅用戶。
200GB FUP，200GB 後不設速度限制，但會降低優先權。
SIM Only 計劃 月費 HK$148 其實係 SIM Only Plan，要簽 24 個月合約。
可選以優惠價 $2,160，購買原價 $3,080 的 SmarTone 5G Wi-Fi 6 路由器。
"""

SMARTONE_HOME_5G_2021_TEXT = """
SmarTone Home 5G Broadband service plan offers a competitive monthly fee of $148,
including a simple plug-and-play set up that saves on installation and relocation charges,
on top of a 7-day trial and return guarantee. With the latest Wi-Fi 6 router that supports
multiple connection, the ultra-fast online experience brought by SmarTone Home 5G Broadband
is 5 to 40 times faster than traditional fixed narrowband service.
"""

SMARTONE_HOME_5G_2021_CHI_TEXT = """
SmarTone Home 5G 寬頻服務開創 5G 私人寬頻新世代。
每月只須$148，即可於家中增加額外私人寬頻。
SmarTone Home 5G寬頻計劃價格極具吸引力，每月只需港幣 148 元，插電即用，更免卻安裝和搬遷費用。
配合支援多裝置連接的 Wi-Fi 6 路由器，帶來比傳統固網窄頻服務快 5 至 40 倍的高速上網體驗。
"""

SMARTONE_HOME_5G_DISNEY_OFFER_CURRENT_TEXT = """
Home 5G Broadband Disney+ Subscription Plans
WiFi 7 Plan $ 217 / Month Originally $308/Month 36-month contract Subscription Offer
Enjoy 12 Months of Disney+ Standard (Value: $1,056) Wi-Fi 7 5G Router Included (Value $3,780)
WiFi 7 Plan $ 229 / Month Originally $308/Month 36-month contract Subscription Offer
Enjoy 12 Months of Disney+ Standard (Value: $1,056) Wi-Fi 7 5G Router Included (Value $3,780) Mesh Router Rental Inclusive
WiFi 6 Plan $ 168 / Month Hot Deal Originally $259/Month 36-month contract Subscription Offer
Enjoy 12 Months of Disney+ Standard (Value: $1,056) Wi-Fi 6 5G Router Included (Value $2,340)
WiFi 6 Plan $ 168 / Month Originally $238/Month 24-month contract Subscription Offer
Enjoy 6 Months of Disney+ Standard (Value: $528) Wi-Fi 6 5G Router Included (Value $1,560)
Home 5G Broadband 36-month Service Plan: Offer average monthly fee HK$168 is calculated based on the original monthly fee HK$259
for Home 5G Broadband plan, after monthly fee rebate HK$91 within the contract period has been given to the customer.
Customer can choose to upgrade to 12-month Disney+ Premium Plan with additional HK$6 Home 5G Broadband monthly fee.
This service plan includes a HK$65 monthly rental fee for router rental service waived within the committed contract period.
Customers are required to make a deposit of HK$1,500 for router rental service.
Home 5G Broadband 24-month Service Plan: Offer average monthly fee HK$168 is calculated based on the original monthly fee HK$238
for Home 5G Broadband plan, after monthly fee rebate HK$70 within the contract period has been given to the customer.
"""

SMARTONE_HOME_5G_DISNEY_OFFER_CURRENT_TC_TEXT = """
盛夏精彩禮遇 Home 5G寬頻 Disney+ 訂閱方案
WiFi 7 計劃 $ 217 / 月 原價 $308/月 36個月合約 上台優惠
請你睇12個月 Disney+ 標準計劃 (總值$1,056) 連Wi-Fi 7 5G路由器 (價值 $3,780)
WiFi 7 計劃 $ 229 / 月 原價 $308/月 36個月合約 上台優惠
請你睇12個月 Disney+ 標準計劃 (總值$1,056) 連Wi-Fi 7 5G路由器 (價值 $3,780) 包括Mesh路由器租用
WiFi 6 計劃 $ 168 / 月 熱門 原價 $258/月 36個月合約 上台優惠
請你睇12個月 Disney+ 標準計劃 (總值$1,056) 連Wi-Fi 6 5G路由器 (價值 $2,340)
WiFi 6 計劃 $ 168 / 月 原價 $238/月 24個月合約 上台優惠
請你睇6個月 Disney+ 標準計劃 (總值$528) 連Wi-Fi 6 5G路由器 (價值 $1,560)
客戶須簽訂指定合約期限及選用指定服務計劃（流動電話月費計劃或Home 5G寬頻服務計劃）。
Home 5G寬頻服務計劃包括路由器租用服務，路由器租用服務之按金為HK$1,500。
"""

SMARTONE_LEARNING_SUPPORT_2022_CHI_TEXT = """
SmarTone Home 5G 寬頻「網課貼心支援計劃」。
獲發政府上網費津貼的本港中小學生，可以$1,600 享用全年無限 5G 數據，
並免費租用 Wi-Fi 6 5G 路由器，一共節省$780 路由器租借費。
「網課貼心支援計劃」 無限 5G 數據 $1,600/年。
"""

SMARTONE_AQUOS_S2_2017_CHI_TEXT = """
SmarTone 獨家推出全新 SHARP AQUOS S2 智能手機。
4.5G 超貼心智能手機計劃
(AQUOS S2 高配版) 月費 本地數據用量 基本通話分鐘 上台機價
$388 6 GB 再送任用數據無限速 4,000 免費
$348 2.5 GB 3,000 免費
$258 1 GB 2,500 $980
(AQUOS S2 標配版) 月費 本地數據用量 基本通話分鐘 上台機價
$348 6 GB 再送任用數據無限速 4,000 免費
$308 2.5 GB 3,000 免費
$218 1 GB 2,500 免費
客戶須簽約 24 個月及繳付每月$18 行政費。
"""

SMARTONE_5G_LAUNCH_2020_TEXT = """
SmarTone 5G Monthly Plan officially launched.
For HK$398/month, customers can enjoy a total of 80GB 5G local data, 2GB GBA roaming data and a 24-month contract.
Selected 5G Monthly Plan customers can enjoy promotional 100GB local data at $398.
SmarTone launched a limited-time offer. For just HK$298 per month for four months, customers can enjoy 100GB 5G local data.
Customers may enjoy up to HK$2100 smartphone discount. iPhone retail price HK$10998 and HK$8898.
5G unlimited local data top-up $80, speed thereafter up to 5Mbps.
Local data top-up $50 10GB.
Add-on SIM $120 50GB.
Monthly admin fee $18. Other value-added services $38, $48 and $69.
"""

SMARTONE_5G_LAUNCH_2020_CHI_TEXT = """
SmarTone 5G 月費計劃具競爭力且非常靈活。每月 港幣 398 元，可享 80GB 本地數據、
2GB 大灣區漫遊數據及內地手機號碼。高用量客戶亦可選擇逐月以每月港幣 80 元升級無限
5G 數據，速度為 5Mbps。登記 5G 服務計劃的客戶，更可於合約期內享每月額外 20GB
本地數據優惠。新客戶合約期內可享 4 個月月費港幣 298 元，餘下合約期內月費港幣
398 元，體驗 100GB 5G 本地數據。5G 本地數據增值 $80/月 無限 或 $50/10GB。
附屬 SIM 咭 第 1 張︰ +$120/月，第 2-4 張： +$120/月，每張額外送 50GB/月 5G 共享本地數據。
"""

SMARTONE_GAMERGIZER_2020_TEXT = """
Gamergizer service average monthly fee $29 after 3-month free service.
SmarTone 5G Monthly Plan table: 100GB local data monthly fee $398.
5G Limited-time Offer $298/month with 100GB local data. Smartphone discount up to HK$2100 and accessories discount HK$1200.
Monthly admin fee $18. Rebate HK$640 and HK$160 are displayed as handset offer components.
5G unlimited local data top-up $80, speed thereafter 5Mbps.
Local data top-up $50 10GB.
Add-on SIM $120 50GB.
"""

SMARTONE_GAMERGIZER_2020_CHI_TEXT = """
SmarTone 5G 爆機王牌平均月費港幣 29 元，首三個月免費試用。
5G 月費計劃月費 $398，可享 100GB 本地數據。
5G 限時優惠 $298/月，可享 100GB 本地數據。
5G 本地數據增值 $80/月 無限 或 $50/10GB。
附屬 SIM 咭 +$120/月，每張額外送 50GB/月 5G 共享本地數據。
"""

SMARTONE_1C2N_2024_CHI_TEXT = """
SmarTone 推出內地及香港「一卡兩號」服務。
現有客戶則可用優惠價$28/月選用此升級服務，並包括 15 分鐘內地語音通話。
"""

SMARTONE_HOME_5G_WIFI7_2025_CHI_TEXT = """
SmarTone Home 5G 寬頻 x Wi-Fi 7 服務正式推出。
客戶可享無限 5G 數據，平均月費只須$191。
"""

HKBN_IQIYI_2023_TC_TEXT = """
香港寬頻與愛奇藝香港攜手推出娛樂優惠。
愛奇藝黃金VIP會員月費為港幣38元，客戶可享每月港幣10元回贈。
愛奇藝鑽石VIP會員月費為港幣58元，客戶可享每月港幣18元回贈。
"""

HKBN_GIGAFAST_TPLINK_2024_TC_TEXT = """
香港寬頻與 TP-Link 合作推出 5Gbps / 10Gbps GigaFast 服務。
指定家居寬頻服務每月只需$698起。
現有指定客戶可每月只需額外加$200起升級至 GigaFast 5Gbps / 10Gbps。
"""

HKBN_HOMEPLUS_5G_2021_TEXT = """
HKBN and HOME+ Bring Shopping Rewards to 5G Mobile Services Customers.
Brand New HKBN 5G Mobile Services Plans
Unlimited Data* Plans Basic Plans
Monthly fee* HK$298 HK$338 HK$238 HK$278
Non existing selected HKBN residential customers Additional HK$10
Data speed 5G
Local data 20GB 30GB 20GB 30GB
Local data speed thereafter Unlimited local data* at 4.5G speeds upon reaching the above 5G local data limit
Top-up local 5G data at HK$388/100GB or HK$30/5GB
Contract period 24 months
Admin fee HK$18
Bonus rewards HK$2,000 e-cash coupons for e-shopping platform HOME+
HK$2,400 e-cash coupons for e-shopping platform HOME+
HK$600 e-cash coupons for e-shopping platform HOME+
HK$800 e-cash coupons for e-shopping platform HOME+
"""

SMARTONE_KONO_TEXT = """
Terms & Conditions for Kono Magazine Service Updated on 30/10/2019.
Service Plan Monthly Service Fee Contract Term Liquidated damages.
Standard Plan (First month free) $38 Not applicable Not applicable.
24-Month Contract Plan (First 4 months free during contract period) $36 24 months $36 x remaining months of the Term.
The fee of the Service Plan is charged on a monthly basis, monthly fee is calculated in Hong Kong Dollars.
"""

HKBN_OEXBN_2026_API_TEXT = json.dumps(
    [
        {
            "planCode": "AX12936HT3M90AN_C338D383690",
            "planName": "1000M Home Broadband Plan with 36-mth Home Telephone",
            "priceInfo": {
                "planPrice": 129,
                "averageFee": 129.0,
                "duration": "36 months contract",
                "PAY_MONTH": 36,
                "charge": [
                    {
                        "serviceName": "1000M Home Broadband Plan with 36-mth Home Telephone",
                        "service": "Broadband Internet",
                        "specialMonthlyFee": "Basic Access Plan 1000M : 1st-36th Month: $129; Prepayment: $200; Monthly Rebate for the 1st to 4th month: $50",
                        "afterContractPeriod": "$368 /month",
                    }
                ],
            },
            "planDetail": [{"cate": "Broadband", "state": True, "heading": "1000M Home Broadband", "contactMonth": "36"}],
        },
        {
            "planCode": "AU14924HTOTAN_C338D3824",
            "planName": "2.5Gbps GigaFast Broadband Plan with 24-mth Home Telephone Service",
            "priceInfo": {
                "planPrice": 149,
                "averageFee": 149.0,
                "duration": "24 months contract",
                "PAY_MONTH": 24,
                "charge": [
                    {
                        "serviceName": "2.5Gbps GigaFast Broadband Plan with 24-mth Home Telephone Service",
                        "service": "Broadband Internet",
                        "specialMonthlyFee": "Basic Access Plan 2.5Gbps GigaFast Broadband: 1st-24th Month: $149",
                        "afterContractPeriod": "$498 /month",
                    }
                ],
            },
            "planDetail": [{"cate": "Broadband", "state": True, "heading": "2.5Gbps GigaFast Broadband Plan", "contactMonth": "24"}],
        },
    ],
    ensure_ascii=False,
)

HKBN_FHKPUAA_2025_TEXT = """
FHKPUAA Cardholders’ Special Offer
1000M Home Broadband Free $680 Installation Fee 365 days Defer start bill
1000M Dual Home Broadband With Choice 1 of 4 Monthly Fee
Disney+ Standard Plan & Free 12-month myTV SUPER Alpha Pack $129
1000M Home Broadband With Mobile Service^ Monthly Fee
With 4.5G 42Mbps 10GB Data Mobile Service Package $159
Plan Details : • 24 months contract period • Promotion period valid until 28 Feb 2025.
2000M / 2.5Gbps Fibre Broadband Free $680 Installation Fee 365 days Defer start bill
2000M Fibre Broadband Plan Monthly Fee
2000M Home Broadband $199
With TP-Link Archer BE230 Wi-Fi 7 Router $229
With OPPO Wi-Fi 6 Router - Spider-Man / Iron Man $239
2.5Gbps GigaFast Broadband Plan Monthly Fee
2500M Home Broadband $228 $199
With TP-Link Archer BE230 Wi-Fi 7 Router $248 $229
Home Broadband with Bowtie 4-In-1 Healthcare Service Plan Monthly Fee Contract
1000M Home Broadband# $109 24 months
Healthcare Service Plan $99 12months
Network Monthly Fee Local Data Extra Benefit
4.5G $98 42Mbps 20GB Thereafter 2 Mbps Unlimited Data
$118 4.5G Full Speed20GB Thereafter 42 Mbps Unlimited Data
5G $98 20GB Thereafter 1 Mbps Unlimited Data
$124 30GB Thereafter 1 Mbps Unlimited Data
$149 50GB Thereafter 1 Mbps Unlimited Data
$162 30GB Thereafter 1 Mbps Unlimited Data + Infinity Local Social & Streaming Data^
Other Details： 1) 24 months contract period 2) Free 3,000 minutes of local airtime per month
3) Waiver of $28 monthly administrative fee during the contract period ($118/$149 monthly fee plan is only applicable to number portability)
HKBN reserves the right to change or cancel the offer and / or Terms & Conditions of service plan at any time without prior notice.
"""

HKBN_FHKPUAA_SEP24_TEXT = """
FHKPUAA Cardholders’ Special Offer
1000M Home Broadband Free $680 Installation Fee 365 days Defer start bill
1000M Dual Home Broadband Monthly With Choice 1 of 3 Fee
Disney+ Standard Plan Free 12-month myTV SUPER Alpha Pack
iQIYI Standard VIP Free 12-month myTV SUPER Alpha Pack
Home Telephone + TP-Link AX23 Wi-Fi 6 Router
$129
1000M Home Broadband With Mobile Service^ Monthly Fee
With 4.5G 42Mbps 10GB Data Mobile Service Package
$159
Plan Details : • 24 months contract period • Promotion period valid until 30 Sep 2024.
2000M / 2500M Fibre Broadband Free $680 Installation Fee 365 days Defer start bill
2500M Fibre Broadband Plan Monthly Fee
2500M Home Broadband $228 $199
With TP-Link Archer BE550 Wi-Fi 7 Router $248 $229
2000M Fibre Broadband Plan Monthly Fee
2000M Home Broadband $199
With TP-Link Archer AX72 Pro Wi-Fi 6 Router $229
With TP-Link Archer BE230 Wi-Fi 7 Router $229
With OPPO Wi-Fi 6 Router - Spider-Man / Iron Man $239
Plan Details : • 24 months contract period
"""

MONEYHERO_BROADBAND_COMPARISON_2025_TEXT = """
光纖入屋 寬頻上網 價錢比較（2025年1月更新）
各大寬頻公司參考收費
寬頻電訊商公司 中國移動 （CMHK） （36個月合約） 【三合一家居寬頻組合】
香港寬頻 （HKBN） （36個月合約） 有線寬頻 （36個月合約） HGC （12個月合約） SmarTone （24個月合約） 網上行 （24個月合約）
網速 1000M 1000M# 1000M# 1000M 1000M 1000M
私人樓宇 （參考價錢） 最低HK$98 最低HK$148 最低HK$68 最低HK$129 最低HK$98 最低HK$138
公屋 （參考價錢） 最低HK$78 最低HK$109 最低HK$68 HK$119 最低HK$88 最低HK$118
記住，以下資料只供參考，最終收費同優惠都要以供應商公布為準。
H3: 1）光纖入屋是甚麼？
"""

HKBN_ROADSHOWOFFER_2500M_148_2025_TEXT = """
Broadband RoadshowOffer public blog/index excerpt verified 2026-07-07.
香港寬頻新入伙屋苑2500M $148 起
香港寬頻新入伙屋苑2500M $148 36 個月 送tplink be230 wifi7 router 送mytv super 24個月基本版智能電視版 送家居電話
"""

HKBN_FINDPLANKING_2500M_149_2026_TEXT = """
Find Plan King 版權所有 © 2026
香港寬頻 已認證 香港寬頻24小時極速專業報價 更新日期：06.07.2026
07月07日網上限時優惠 新裝/轉台/續約 歡迎查詢
2500M獨享Giga Fast光纖入屋【 月費💰149 】 💢24個月合約
免安裝費 送6個月F-Secure防毒 送家居電話服務24個月
送 myTV SUPER基本版(智能電視版) 12個月 送原裝行貨 WiFi 7 TPLink Deco BE25-兩件裝
"""

HKBN_PRICEQUOTE_POSTS_2500M_149_2026_TEXT = """
Broadband-PriceQuote 寬頻報價 Blog/Posts
『HKBN vs HGC 1000M/2500M優惠比較︱最新寬頻報價2026』
香港寬頻 HKBN 1000M/2500M報價私樓住戶優惠：目標住宅：私人住宅用戶，1000MB 光纖入屋，月費：$109，合約期：24個月。
公屋/居屋專屬優惠：目標住宅：公屋、居屋居民，1000MB 光纖入屋，月費：$98，合約期：24個月。
香港寬頻 HKBN 2500M報價 極速網絡：2500M 對稱上下載速度 基礎月費：$149 合約期：24個月 安裝費：全免。
HKBN 2500M 機皇(149)：簽24個月只需149。除咗送TP-Link BE230 Wi-Fi 7 Router，仲包埋24 個月家居電話、6 個月防毒Apps 及60 日旅遊卡。
資料只供參考，實際收費及優惠由供應商合約內容為準。
"""

BOOGA_BROADBAND_COMPARISON_2025_TEXT = """
各大寬頻優惠比較 + 轉台/續約 + $68 長者寬頻優惠｜附最新網上行、中國移動、HGC、有線、香港寬頻優惠
更新於: 2025年9月14日
HKBN 香港寬頻優惠 1000M 寬頻
HKBN 香港寬頻 1000M 寬頻優惠
戶型 寬頻速度 合約期 參考月費 安裝費
公屋/居屋 1000M 36 個月 HK$98 豁免
私樓 1000M 36 個月 HK$109 豁免
比較所有 HKBN 香港寬頻 1000M 寬頻優惠
HGC/和記/環電寬頻優惠 1000M 寬頻
HGC/和記/環電 1000M 寬頻優惠
戶型 寬頻速度 合約期 參考月費 安裝費
公屋/居屋 1000M 36 個月 HK$89 豁免
私樓 1000M 36 個月 HK$109 $180
比較所有 HGC/和記/環電寬頻 1000M 寬頻優惠
CMHK中國移動優惠 1000M 寬頻
有線寬頻 i-cable 優惠 1000M 寬頻
有線寬頻 i-cable 寬頻 1000M 寬頻優惠
戶型 寬頻速度 合約期 參考月費 安裝費
公屋/居屋 1000M 36 個月 HK$88 豁免
私樓 1000M 36 個月 HK$88 豁免
長者寬頻優惠：長者上網寬頻優惠 200M 寬頻
"""

BOOGA_ICABLE_2026_TEXT = """
有線寬頻好唔好？$68 最平寬頻登場！Booga 拆解 1000M/2000M 計劃
更新於: 2026年4月13日
事隔 10 年，i cable 帶著「$68 最平寬頻」重返戰場，更推出極具競爭力嘅 $88 1000M 寬頻、$118 2000M 寬頻計劃。
Booga 獨家：有線寬頻 10 大公居屋/私樓計劃 - $68 最平寬頻之選！
【$68 入門之選】公居屋/私樓 200M 計劃 月費： $68 合約期： 36 個月 上網速度： 200M 適用： 公居屋 / 私樓
【$68 / $88 性價比最高】1000M 寬頻計劃 (36 vs 48 個月點揀？)
計劃 (A) - $88 / 36個月 (公居屋/私樓) 適用： 公居屋 / 私樓
計劃 (B) - $88 / 48個月 (私樓限定 - 送 Router) 適用： 私樓
計劃 (C) - $68 / 48個月 (指定公居屋) 適用： 指定公居屋
【$118 高速之選】公居屋/私樓 2000M 寬頻計劃 月費： $118 合約期： 36 個月 上網速度： 2000M 適用： 公居屋 / 私樓
"""

BOOGA_PUBLIC_HOUSING_BROADBAND_2025_TEXT = """
公屋/居屋寬頻上網比較｜最新 2024/ 2025 最平光纖寬頻優惠
更新於: 2025年10月11日
公屋及居屋 光纖寬頻上網月費比較
供應商 速度 平均月費 合約期 安裝費 詳情 優惠
香港寬頻 HKBN 1000M $109 36 個月 豁免
有線寬頻 iCable 200M $68 36 個月 豁免 另有 2000M 月費 $118 合約期內滿 3 個月免一次搬遷費
中國移動 CMHK 1000M $78 36 個月 豁免
網上行 Netvigator 1000M $98 36 個月 豁免
和記 HGC 1000M $89 36 個月 豁免
"""

INVESTBROTHER_BROADBAND_COMPARISON_2025_TEXT = """
香港家居寬頻比較2026｜家居寬頻月費、合約期、家居寬頻優惠比較
最近更新：2025 年 9 月 5 日
家居寬頻比較|HKBN香港寬頻1000M計劃
公屋月費 HK$109 私人住宅月費 HK$149 合約期 36個月 豁免安裝費
家居寬頻比較|HKBN香港寬頻2500M計劃
公屋月費 HK$149 私人住宅月費 HK$149 合約期 24個月 豁免安裝費
家居寬頻比較|HKBN香港寬頻10G計劃
公屋月費 HK$169 私人住宅月費 HK$169 合約期 24個月 豁免安裝費
家居寬頻比較|HGC寬頻1000M計劃
公屋月費 HK$89 私人住宅月費 HK$109 合約期 36個月 豁免安裝費
家居寬頻比較|HGC寬頻2200M計劃
公屋月費 HK$139 私人住宅月費 HK$149 合約期 36個月 豁免安裝費
家居寬頻比較|有線寬頻1000M計劃
公屋月費 HK$88 私人住宅月費 HK$88 合約期 36個月 豁免安裝費
家居寬頻比較|SmarTone 1000M計劃
公屋月費 HK$88 私人住宅月費 HK$98 合約期 36個月 豁免安裝費
條款及細則 以上價格及優惠內容作參考，詳情請查閱官網。
家居寬頻比較|網上行Netvigator
"""

MONEYSMART_BROADBAND_COMPARISON_2026_TEXT = """
MoneySmart 寬頻上網比較2026｜光纖入屋價錢＋合約期+優惠比較
資料截至2026年5月3日
HKBN: 2.5Gbps GigaFast HK$169/month, 2.5Gbps with Wi-Fi 7 router HK$199/month, 1Gbps with Wi-Fi 6 router HK$149/month.
SmarTone 光纖寬頻: 1000Mbps HK$98/月 24個月, 2Gbps/2.2Gbps HK$128/月 36個月,
2Gbps/2.2Gbps + Wi-Fi 7 HK$148/月 36個月, 2Gbps/2.2Gbps + Wi-Fi 6 HK$154/月 36個月.
HGC 光纖寬頻: Wi-Fi 6路由器 X 1G 寬頻服務 HK$129/月 36個月;
myTV Gold X 1G 寬頻服務 HK$198/月 36個月; hmvod X 1G 寬頻服務 HK$119/月 36個月;
Wi-Fi 7路由器 X 2G 寬頻服務 HK$189/月 24個月; Wi-Fi 7路由器 X 2G 寬頻服務 HK$199/月 24個月.
i-CABLE: 1000M HK$88起, 2x1000M HK$98起, 200M HK$68起.
"""

FIBREHK_ISP_COMPARISON_2026_TEXT = """
HKBN vs HGC vs SmarTone vs CMHK vs i-Cable vs HKT: A Full Comparison of Hong Kong's Major ISPs in 2026
2. Price Comparison (1000M Plans)
The table below compares typical monthly fees for 1000M plans on a 24-month contract:
Provider Monthly Fee (approx.) Installation Router Notes
HKBN HK$158 Free Free loan New customer promo price
HGC HK$168 Free Free loan Lower in select estates
SmarTone HK$178 Free Free loan $20 off with mobile bundle
CMHK HK$128 Free Free loan Limited-time promo price
i-Cable HK$168 Free Rental $18/mo Better value with cable TV
HKT HK$198 Free Free loan Can bundle with Now TV
Note: Prices shown are indicative as of March 2026. Actual pricing varies by district, building, and promotional offers.
"""

YAHOO_BROADBAND_COMPARISON_2026_TEXT = """
Yahoo 香港 家居寬頻推介及優惠比較. Public Yahoo HK article excerpt verified 2026-07-06.
Published 2026-01-06 / updated 2026-06-30 in Yahoo search/opened article metadata.
香港寬頻 家居寬頻 1000M 公屋/居屋 HK$88/月 36個月合約；私人住宅 HK$109/月 36個月合約.
HGC Broadband 家居寬頻 1000M 公屋/居屋 HK$119/月 36個月合約；私人住宅 HK$129/月 36個月合約.
SmarTone 家居寬頻 1000M 公屋/居屋 HK$88/月 36個月合約；私人住宅 HK$98/月 36個月合約.
i-CABLE 家居寬頻 1000M 公屋/居屋 HK$88/月 36個月合約；私人住宅 HK$118/月 36個月合約.
"""

SHANGTAIKA_BROADBAND_COMPARISON_2026_TEXT = """
全港寬頻上網優惠比較平台
資料更新於2026年6月
香港寬頻 1000M HK$109起 36個月
香港寬頻 2.5G/2.5Gbps HK$199 24個月
香港寬頻 2.5G HK$169 24個月
SmarTone 智能家居光纖寬頻 公屋/居屋 1000M HK$88起 36個月
SmarTone 1000M HK$98 36個月
SmarTone 2G HK$128 36個月
SmarTone 2.2G HK$128 36個月
有線寬頻 200M HK$68起
有線寬頻 100M HK$68起
有線寬頻 1000M HK$89起
有線寬頻 2000M HK$129起
"""

QUOQUO_BROADBAND_COMPARISON_2026_TEXT = """
寬頻月費比較(光纖/5G) 3/2026
日期: 2026-03-09 15:03
共7間供應商嘅服務收費，當中包括香港寬頻(HKBN)、HGC寬頻、數碼通(SmarTone)。
更新: 09/3/2026
(3) 公屋居屋 2000M 或以上
公司 平均月費 合約期 禮品
數碼通
特選屋苑 $118 / 2000M -2200M * 36
$128 / 2000M -2200M * 36
「按此打開備註 / 查詢詳情」
* 視乎覆蓋
**據了解，數碼通會租用其他公司網絡**
(5) 5G家居寬頻
數碼通 $148 $168 連一年Disney Plus 5G 路由器: 免費租用 WiFi 6 24
"""

HKTECHREVIEW_BROADBAND_COMPARISON_2025_TEXT = """
6大電訊商家居寬頻比較2026 - HKTechReview
12 December 2025
1000M家居寬頻比較
電訊商
1000M家居寬頻最低月費
安裝費
中國移動
HK$78（36個月合約）
香港寬頻
HK$88（24個月合約）
SmarTone
HK$88（36個月合約）
有線寬頻
HK$88（36個月合約）
HGC環電
公屋：HK$109（24個月合約）
私樓：HK$119（36個月合約）
HK$180
資料截至2025年12月11日，表格中的價格和套餐資訊可能會隨時間改變，請以電訊商網站公佈的最新價格和套餐資訊為準。
"""

HKBN_HOMEPLUS_TECHENT_2021_TEXT = """
HKBN and HOME+ Join Forces to Deliver Breakthrough Shopping Rewards to 5G Mobile Services Customers
HONG KONG, April 23, 2021. Brand New HKBN 5G Mobile Services Plans
Unlimited Data Plans Basic Plans
Monthly fee HK$298 HK$338 HK$238 HK$278
Data speed 5G
Local data 20GB 30GB 20GB 30GB
Top-up local 5G data at HK$388/100GB or HK$30/5GB
Contract period 24 months
Admin fee HK$18
"""

HKBN_CROSSBORDER_5G_2023_TEXT = """
HKBN Launches Cross-border 5G Local + 1GB GBA Data Plans.
These all-in-one plans will allow enterprise and personal customers to enjoy either
10GB 5G local data + 1GB mainland China and Macau roaming data per month for as low as HK$103/month;
or 30GB 5G local data + 1GB mainland China and Macau roaming data for only HK$149/month.
When more roaming data in mainland China and Macau is required, customers can get an additional 2GB for only HK$38.
All of the above plans will include a monthly administration fee of HK$28.
"""

HGC_25G_2023_TEXT = """
HGC Broadband launches 2.5G broadband service for households.
3-year 2.5G broadband service plus 2 sets of TP-Link Deco XE75 Pro Wi-Fi 6 router
at a monthly fee of HK$298* (Mesh network compatible; installation and maintenance included).
Additional HK$30/month* for Home Telephone service.
Existing customers upgrade to 2.5G service available.
"""

HGC_TERMS_TC_2026_TEXT = """
和記環球電訊家居寬頻服務條款及細則
6Mbps 、 10Mbps 、 30Mbps 、 100Mbps 、 200Mbps 、 300Mbps 、 500Mbps 、1Gbps、2Gbps、 2.2Gbps、 2.5Gbps 及 10Gbps寬頻服務之正價月費分別為 $188 、 $188 、 $198 、 $298 、 $348 、 $398 、 $448 、 $598、 $666 、 $666 、 $766 及 $1,299 ( 未包括增值服務費 ) 。
"""

SMARTONE_AQUOS_PCM_2017_TEXT = """
拎舊 Sharp 手機可上台半價買 AQUOS S2
AQUOS S2 高配版出機計劃
月費 本地數據量 基本通話分鐘 上台機價
$388 6GB（送任用數據無限速） 4,000mins $0（預繳 $3,980）
$348 2.5GB 3,000mins $0（預繳 $3,980）
$258 1GB 2,500mins $980（預繳 $3,000）
要簽 24 個月、每月 $18 行政費。
"""


class HkCompetitorProductCrawlTest(unittest.TestCase):
    def test_normalise_hgc_wifi6_prnasia_broadband_fields(self) -> None:
        row = _normalise_plan_row(
            {
                "period_label": "2022",
                "brand": "HGC",
                "product_category": "home_fibre_broadband",
                "service_generation": "5G",
                "plan_family": "HGC on air",
                "plan_name": "HGC on air HK$119",
                "monthly_fee_hkd": "119",
                "average_monthly_fee_hkd": "",
                "local_data_gb": "",
                "broadband_speed_mbps": "1000",
                "source_id": "hgc_wifi6_2022_press",
                "source_url": "https://enmobile.prnasia.com/releases/apac/hgc-broadband-launches-wi-fi-6-router-service-for-hong-kong-households-355741.shtml",
            }
        )

        self.assertEqual(row["source_id"], "hgc_wifi6_router_2022_prnasia")
        self.assertEqual(row["service_generation"], "Fibre/Broadband")
        self.assertEqual(row["plan_family"], "HGC Home Broadband")
        self.assertEqual(row["plan_name"], "HGC Home Broadband HK$119")

    def test_parse_current_product_price_rows(self) -> None:
        source = {
            "source_id": "3hk_5g_sim_plan",
            "brand": "3HK / Hutchison",
            "product_category": "mobile_consumer_5g",
            "url": "https://web.three.com.hk/plans/5g/index-en.html",
        }
        rows = _parse_page(source, {"status": 200, "text": THREE_TEXT}, "2026-07-02T00:00:00+08:00", "current")
        by_fee = {row["monthly_fee_hkd"]: row for row in rows}
        self.assertEqual(by_fee["124"]["local_data_gb"], "30")
        self.assertEqual(by_fee["48"]["roaming_data_gb"], "20")
        self.assertEqual(by_fee["124"]["source_status"], "parsed_current")

    def test_parse_moneyhero_2025_broadband_comparison_rows(self) -> None:
        source = {
            "source_id": "hgc_moneyhero_broadband_comparison_2025",
            "brand": "HGC",
            "product_category": "home_fibre_broadband",
            "url": "https://www.moneyhero.com.hk/zh/credit-card/blog/test",
        }
        rows = _parse_page(source, {"status": 200, "text": MONEYHERO_BROADBAND_COMPARISON_2025_TEXT}, "2026-07-03T00:00:00+08:00", "2025")
        by_fee = {row["monthly_fee_hkd"]: row for row in rows}

        self.assertEqual(set(by_fee), {"129", "119"})
        self.assertEqual(by_fee["129"]["broadband_speed_mbps"], "1000")
        self.assertEqual(by_fee["129"]["contract_months"], "12")
        self.assertEqual(by_fee["119"]["source_status"], "public_third_party_comparison_needs_review")

    def test_parse_moneyhero_2025_hkbn_gigafast_2500m_reference_row(self) -> None:
        source = {
            "source_id": "hkbn_moneyhero_broadband_comparison_2025",
            "brand": "HKBN",
            "product_category": "home_fibre_broadband",
            "url": "https://www.moneyhero.com.hk/zh/credit-card/blog/test",
        }
        rows = _parse_page(source, {"status": 200, "text": MONEYHERO_BROADBAND_COMPARISON_2025_TEXT}, "2026-07-07T00:00:00+08:00", "2025")
        by_fee = {row["monthly_fee_hkd"]: row for row in rows}

        self.assertEqual(by_fee["148"]["broadband_speed_mbps"], "2500")
        self.assertIn("2500M", by_fee["148"]["plan_name"])
        self.assertEqual(by_fee["148"]["customer_segment"], "private_building_reference")
        self.assertEqual(by_fee["109"]["broadband_speed_mbps"], "1000")
        self.assertEqual(by_fee["109"]["customer_segment"], "public_housing_reference")

    def test_parse_hkbn_roadshowoffer_2500m_148_2025_row(self) -> None:
        source = {
            "source_id": "hkbn_broadband_roadshowoffer_2500m_148_2025",
            "brand": "HKBN",
            "product_category": "home_fibre_broadband",
            "url": "https://www.broadband-roadshowoffer.com/blog",
            "period_label": "2025",
        }
        rows = _parse_page(source, {"status": 200, "text": HKBN_ROADSHOWOFFER_2500M_148_2025_TEXT}, "2026-07-07T00:00:00+08:00", "2025")
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["monthly_fee_hkd"], "148")
        self.assertEqual(row["broadband_speed_mbps"], "2500")
        self.assertEqual(row["contract_months"], "36")
        self.assertEqual(row["source_status"], "public_third_party_channel_reference_needs_review")

    def test_parse_hkbn_findplanking_2500m_149_2026_row(self) -> None:
        source = {
            "source_id": "hkbn_findplanking_2500m_149_2026",
            "brand": "HKBN",
            "product_category": "home_fibre_broadband",
            "url": "https://findplanking.com/broadband/-Ma4eTavqkvwIHSFy5_i",
            "period_label": "2026",
        }
        rows = _parse_page(source, {"status": 200, "text": HKBN_FINDPLANKING_2500M_149_2026_TEXT}, "2026-07-07T00:00:00+08:00", "2026")
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["monthly_fee_hkd"], "149")
        self.assertEqual(row["broadband_speed_mbps"], "2500")
        self.assertEqual(row["contract_months"], "24")
        self.assertEqual(row["source_status"], "public_third_party_offer_listing_needs_review")

    def test_parse_hkbn_pricequote_posts_2500m_149_2026_rows(self) -> None:
        source = {
            "source_id": "hkbn_pricequote_posts_2500m_149_2026",
            "brand": "HKBN",
            "product_category": "home_fibre_broadband",
            "url": "https://www.broadband-pricequote.com/posts",
            "period_label": "2026",
        }
        rows = _parse_page(source, {"status": 200, "text": HKBN_PRICEQUOTE_POSTS_2500M_149_2026_TEXT}, "2026-07-08T00:00:00+08:00", "2026")
        self.assertEqual(len(rows), 2)
        self.assertEqual({row["customer_segment"] for row in rows}, {"private_building_reference", "public_housing_reference"})
        for row in rows:
            self.assertEqual(row["monthly_fee_hkd"], "149")
            self.assertEqual(row["broadband_speed_mbps"], "2500")
            self.assertEqual(row["contract_months"], "24")
            self.assertEqual(row["local_voice"], "home telephone service included")
            self.assertEqual(row["source_status"], "public_third_party_channel_reference_needs_review")

    def test_parse_booga_2025_broadband_comparison_rows(self) -> None:
        source = {
            "source_id": "hkbn_booga_broadband_comparison_2025",
            "brand": "HKBN",
            "product_category": "home_fibre_broadband",
            "url": "https://booga.com.hk/en/blog/test",
        }
        rows = _parse_page(source, {"status": 200, "text": BOOGA_BROADBAND_COMPARISON_2025_TEXT}, "2026-07-03T00:00:00+08:00", "2025")
        by_fee = {row["monthly_fee_hkd"]: row for row in rows}

        self.assertEqual(set(by_fee), {"98", "109"})
        self.assertEqual(by_fee["109"]["broadband_speed_mbps"], "1000")
        self.assertEqual(by_fee["109"]["customer_segment"], "private_building_reference")
        self.assertEqual(by_fee["109"]["contract_months"], "36")
        self.assertEqual(by_fee["98"]["source_status"], "public_third_party_comparison_needs_review")

    def test_parse_booga_2025_icable_private_and_public_segments(self) -> None:
        source = {
            "source_id": "icable_booga_broadband_comparison_2025",
            "brand": "i-CABLE",
            "product_category": "home_fibre_broadband",
            "url": "https://booga.com.hk/en/blog/test",
        }
        rows = _parse_page(source, {"status": 200, "text": BOOGA_BROADBAND_COMPARISON_2025_TEXT}, "2026-07-03T00:00:00+08:00", "2025")
        by_segment = {row["customer_segment"]: row for row in rows}

        self.assertEqual(set(by_segment), {"public_housing_reference", "private_building_reference"})
        self.assertEqual(by_segment["private_building_reference"]["monthly_fee_hkd"], "88")
        self.assertEqual(by_segment["private_building_reference"]["broadband_speed_mbps"], "1000")
        self.assertEqual(by_segment["private_building_reference"]["contract_months"], "36")

    def test_parse_booga_2025_hgc_snapshot_title_variant(self) -> None:
        source = {
            "source_id": "hgc_booga_broadband_comparison_2025",
            "brand": "HGC",
            "product_category": "home_fibre_broadband",
            "url": "https://booga.com.hk/en/blog/test",
        }
        text = """
        Booga broadband comparison public article excerpt verified 2026-07-08.
        各大寬頻優惠比較 + 轉台/續約 + $68 長者寬頻優惠；更新於: 2025年9月14日.
        HKBN 香港寬頻 1000M 寬頻優惠: 公屋/居屋 1000M 36 個月 HK$98 豁免；私樓 1000M 36 個月 HK$109 豁免.
        HGC/和記/環電 1000M 寬頻優惠: 公屋/居屋 1000M 36 個月 HK$89 豁免；私樓 1000M 36 個月 HK$109 $180.
        CMHK中國移動優惠 1000M 寬頻.
        """
        rows = _parse_page(source, {"status": 200, "text": text}, "2026-07-08T00:00:00+08:00", "2025")
        by_segment = {row["customer_segment"]: row for row in rows}

        self.assertEqual(set(by_segment), {"public_housing_reference", "private_building_reference"})
        self.assertEqual(by_segment["public_housing_reference"]["monthly_fee_hkd"], "89")
        self.assertEqual(by_segment["private_building_reference"]["monthly_fee_hkd"], "109")
        self.assertEqual(by_segment["private_building_reference"]["contract_months"], "36")

    def test_parse_booga_icable_2026_broadband_offer_rows(self) -> None:
        source = {
            "source_id": "icable_booga_2026_current_broadband_offer",
            "brand": "i-CABLE",
            "product_category": "home_fibre_broadband",
            "url": "https://booga.com.hk/zh-HK/blog/test",
        }
        rows = _parse_page(source, {"status": 200, "text": BOOGA_ICABLE_2026_TEXT}, "2026-07-06T00:00:00+08:00", "2026")
        by_segment = {row["customer_segment"]: row for row in rows}

        self.assertEqual(len(rows), 5)
        self.assertEqual(by_segment["entry_200m_public_private_reference"]["monthly_fee_hkd"], "68")
        self.assertEqual(by_segment["entry_200m_public_private_reference"]["broadband_speed_mbps"], "200")
        self.assertEqual(by_segment["value_1000m_public_private_reference"]["contract_months"], "36")
        self.assertEqual(by_segment["router_1000m_private_reference"]["contract_months"], "48")
        self.assertEqual(by_segment["hidden_1000m_public_reference"]["monthly_fee_hkd"], "68")
        self.assertEqual(by_segment["speed_2000m_public_private_reference"]["broadband_speed_mbps"], "2000")
        self.assertEqual(rows[0]["source_status"], "public_third_party_offer_listing_needs_review")

    def test_parse_icable_service_wifi_2026_official_row(self) -> None:
        source = {
            "source_id": "icable_service_wifi_2026_official",
            "brand": "i-CABLE",
            "product_category": "home_fibre_broadband",
            "url": "https://service.i-cable.com/tc/wifi",
            "period_label": "2026",
        }
        rows = _parse_page(source, {"status": 200, "text": ICABLE_SERVICE_WIFI_2026_TEXT}, "2026-07-07T00:00:00+08:00", "2026")
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["monthly_fee_hkd"], "93")
        self.assertEqual(row["broadband_speed_mbps"], "1000")
        self.assertEqual(row["contract_months"], "36")
        self.assertEqual(row["source_status"], "official_public_page_js_text_snapshot")

    def test_parse_icable_telcoquo_1000m_89_2026_row(self) -> None:
        source = {
            "source_id": "icable_telcoquo_1000m_89_2026",
            "brand": "i-CABLE",
            "product_category": "home_fibre_broadband",
            "url": "https://telcoquo.com/broadbandoffers/test",
            "period_label": "2026",
        }
        rows = _parse_page(source, {"status": 200, "text": ICABLE_TELCOQUO_1000M_89_2026_TEXT}, "2026-07-07T00:00:00+08:00", "2026")
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["monthly_fee_hkd"], "89")
        self.assertEqual(row["broadband_speed_mbps"], "1000")
        self.assertEqual(row["customer_segment"], "market_reference")
        self.assertEqual(row["source_status"], "public_third_party_indexed_offer_needs_review")

    def test_parse_icable_telcoquo_1000m_118_2026_private_building_row(self) -> None:
        source = {
            "source_id": "icable_telcoquo_1000m_118_2026",
            "brand": "i-CABLE",
            "product_category": "home_fibre_broadband",
            "url": "https://telcoquo.com/%E4%BD%8F%E5%AE%85%E5%AF%AC%E9%A0%BB%E5%A0%B1%E5%83%B9%E5%88%86%E4%BA%AB/",
            "period_label": "2026",
        }
        rows = _parse_page(source, {"status": 200, "text": ICABLE_TELCOQUO_1000M_118_2026_TEXT}, "2026-07-07T00:00:00+08:00", "2026")
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["monthly_fee_hkd"], "118")
        self.assertEqual(row["broadband_speed_mbps"], "1000")
        self.assertEqual(row["customer_segment"], "private_building_reference")
        self.assertEqual(row["source_status"], "public_third_party_indexed_offer_needs_review")

    def test_parse_icable_broadband_pricequote_1000m_68_2023_public_housing_row(self) -> None:
        source = {
            "source_id": "icable_broadband_pricequote_1000m_68_2023",
            "brand": "i-CABLE",
            "product_category": "home_fibre_broadband",
            "url": "https://www.broadband-pricequote.com/post/icable1000m-1023",
            "period_label": "2023",
        }
        rows = _parse_page(source, {"status": 200, "text": ICABLE_BROADBAND_PRICEQUOTE_1000M_68_2023_TEXT}, "2026-07-08T00:00:00+08:00", "2023")
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["monthly_fee_hkd"], "68")
        self.assertEqual(row["broadband_speed_mbps"], "1000")
        self.assertEqual(row["contract_months"], "36")
        self.assertEqual(row["customer_segment"], "public_housing_reference")
        self.assertEqual(row["source_status"], "public_third_party_channel_reference_needs_review")

    def test_parse_booga_public_housing_icable_broadband_comparison_rows(self) -> None:
        source = {
            "source_id": "icable_booga_public_housing_broadband_comparison_2025",
            "brand": "i-CABLE",
            "product_category": "home_fibre_broadband",
            "url": "https://booga.com.hk/zh-HK/blog/test",
        }
        rows = _parse_page(source, {"status": 200, "text": BOOGA_PUBLIC_HOUSING_BROADBAND_2025_TEXT}, "2026-07-06T00:00:00+08:00", "2025")
        by_speed = {row["broadband_speed_mbps"]: row for row in rows}

        self.assertEqual(set(by_speed), {"200", "2000"})
        self.assertEqual(by_speed["200"]["monthly_fee_hkd"], "68")
        self.assertEqual(by_speed["2000"]["monthly_fee_hkd"], "118")
        self.assertEqual(by_speed["200"]["contract_months"], "36")
        self.assertEqual(by_speed["2000"]["source_status"], "public_third_party_comparison_needs_review")

    def test_parse_smartone_investbrother_2025_broadband_comparison_rows(self) -> None:
        cases = [
            ("smartone_investbrother_broadband_comparison_2025", "SmarTone", {("1000", "98"), ("1000", "88")}),
            (
                "hkbn_investbrother_broadband_comparison_2025",
                "HKBN",
                {("1000", "109"), ("1000", "149"), ("2500", "149"), ("10000", "169")},
            ),
            ("hgc_investbrother_broadband_comparison_2025", "HGC", {("1000", "89"), ("1000", "109"), ("2500", "139"), ("2500", "149")}),
            ("icable_investbrother_broadband_comparison_2025", "i-CABLE", {("1000", "88")}),
        ]
        for source_id, brand, expected in cases:
            source = {
                "source_id": source_id,
                "brand": brand,
                "product_category": "home_fibre_broadband",
                "url": "https://www.investbrother.com/brother-academy/broadband-comparison/",
            }
            rows = _parse_page(source, {"status": 200, "text": INVESTBROTHER_BROADBAND_COMPARISON_2025_TEXT}, "2026-07-03T00:00:00+08:00", "2025")
            speed_fee = {(row["broadband_speed_mbps"], row["monthly_fee_hkd"]) for row in rows}

            self.assertEqual(speed_fee, expected)
            self.assertTrue(all(row["source_status"] == "public_third_party_comparison_needs_review" for row in rows))

    def test_parse_moneysmart_2026_broadband_comparison_rows(self) -> None:
        source = {
            "source_id": "smartone_moneysmart_broadband_comparison_2026",
            "brand": "SmarTone",
            "product_category": "home_fibre_broadband",
            "url": "https://blog.moneysmart.hk/zh-hk/credit-cards/broadband",
            "period_label": "2026",
        }
        rows = _parse_page(source, {"status": 200, "text": MONEYSMART_BROADBAND_COMPARISON_2026_TEXT}, "2026-07-06T00:00:00+08:00", "2026")
        by_speed_fee = {(row["broadband_speed_mbps"], row["monthly_fee_hkd"]): row for row in rows}

        self.assertEqual(len(rows), 5)
        self.assertEqual(by_speed_fee[("1000", "98")]["contract_months"], "24")
        self.assertEqual(by_speed_fee[("2000", "128")]["customer_segment"], "market_reference")
        self.assertEqual(by_speed_fee[("2200", "148")]["contract_months"], "36")
        self.assertEqual(by_speed_fee[("2200", "154")]["contract_months"], "36")
        self.assertEqual(by_speed_fee[("2200", "148")]["add_on_charges_hkd"], "Wi-Fi 7 router bundle")
        self.assertNotIn(("2500", "178"), by_speed_fee)
        self.assertEqual(rows[0]["source_status"], "public_third_party_comparison_needs_review")

        hkbn_source = dict(source, source_id="hkbn_moneysmart_broadband_comparison_2026", brand="HKBN")
        hkbn_rows = _parse_page(hkbn_source, {"status": 200, "text": MONEYSMART_BROADBAND_COMPARISON_2026_TEXT}, "2026-07-06T00:00:00+08:00", "2026")
        self.assertEqual({(row["broadband_speed_mbps"], row["monthly_fee_hkd"]) for row in hkbn_rows}, {("2500", "169"), ("2500", "199"), ("1000", "149")})

        hgc_source = dict(source, source_id="hgc_moneysmart_broadband_comparison_2026", brand="HGC")
        hgc_rows = _parse_page(hgc_source, {"status": 200, "text": MONEYSMART_BROADBAND_COMPARISON_2026_TEXT}, "2026-07-06T00:00:00+08:00", "2026")
        hgc_by_speed_fee = {(row["broadband_speed_mbps"], row["monthly_fee_hkd"]): row for row in hgc_rows}
        self.assertEqual(set(hgc_by_speed_fee), {("1000", "129"), ("1000", "198"), ("1000", "119"), ("2000", "189"), ("2000", "199")})
        self.assertEqual(hgc_by_speed_fee[("1000", "129")]["contract_months"], "36")
        self.assertEqual(hgc_by_speed_fee[("1000", "198")]["contract_months"], "36")
        self.assertEqual(hgc_by_speed_fee[("1000", "119")]["contract_months"], "36")
        self.assertEqual(hgc_by_speed_fee[("2000", "189")]["contract_months"], "24")
        self.assertEqual(hgc_by_speed_fee[("2000", "199")]["contract_months"], "24")

        icable_source = dict(source, source_id="icable_moneysmart_broadband_comparison_2026", brand="i-CABLE")
        icable_rows = _parse_page(icable_source, {"status": 200, "text": MONEYSMART_BROADBAND_COMPARISON_2026_TEXT}, "2026-07-06T00:00:00+08:00", "2026")
        self.assertEqual({(row["broadband_speed_mbps"], row["monthly_fee_hkd"]) for row in icable_rows}, {("1000", "88"), ("2000", "98"), ("200", "68")})

    def test_parse_fibrehk_2026_icable_isp_comparison_row(self) -> None:
        source = {
            "source_id": "icable_fibrehk_isp_comparison_2026",
            "brand": "i-CABLE",
            "product_category": "home_fibre_broadband",
            "url": "https://fibrebroadbandprice.com/en/blog/hkbn-vs-hgc-vs-smartone-comparison",
            "period_label": "2026",
        }
        rows = _parse_page(source, {"status": 200, "text": FIBREHK_ISP_COMPARISON_2026_TEXT}, "2026-07-06T00:00:00+08:00", "2026")

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["monthly_fee_hkd"], "168")
        self.assertEqual(row["broadband_speed_mbps"], "1000")
        self.assertEqual(row["contract_months"], "24")
        self.assertIn("indicative", row["evidence_excerpt"])

    def test_parse_yahoo_2026_broadband_comparison_rows(self) -> None:
        cases = [
            ("hkbn_yahoo_broadband_comparison_2026", "HKBN", {("88", "public_housing_reference"), ("109", "private_building_reference")}),
            ("hgc_yahoo_broadband_comparison_2026", "HGC", {("119", "public_housing_reference"), ("129", "private_building_reference")}),
            ("smartone_yahoo_broadband_comparison_2026", "SmarTone", {("88", "public_housing_reference"), ("98", "private_building_reference")}),
            ("icable_yahoo_broadband_comparison_2026", "i-CABLE", {("88", "public_housing_reference"), ("118", "private_building_reference")}),
        ]
        for source_id, brand, expected in cases:
            source = {
                "source_id": source_id,
                "brand": brand,
                "product_category": "home_fibre_broadband",
                "url": "https://hk.news.yahoo.com/broadband",
                "period_label": "2026",
            }
            rows = _parse_page(source, {"status": 200, "text": YAHOO_BROADBAND_COMPARISON_2026_TEXT}, "2026-07-06T00:00:00+08:00", "2026")
            self.assertEqual({(row["monthly_fee_hkd"], row["customer_segment"]) for row in rows}, expected)
            self.assertEqual({row["broadband_speed_mbps"] for row in rows}, {"1000"})
            self.assertEqual({row["contract_months"] for row in rows}, {"36"})
            self.assertTrue(all(row["source_status"] == "public_media_comparison_needs_review" for row in rows))

    def test_parse_shangtaika_2026_broadband_comparison_rows(self) -> None:
        cases = [
            ("hkbn_shangtaika_broadband_comparison_2026", "HKBN", {("1000", "109"), ("2500", "199"), ("2500", "169")}),
            ("smartone_shangtaika_broadband_comparison_2026", "SmarTone", {("1000", "88"), ("1000", "98"), ("2000", "128"), ("2200", "128")}),
            ("icable_shangtaika_broadband_comparison_2026", "i-CABLE", {("200", "68"), ("100", "68"), ("1000", "89"), ("2000", "129")}),
        ]
        for source_id, brand, expected in cases:
            source = {
                "source_id": source_id,
                "brand": brand,
                "product_category": "home_fibre_broadband",
                "url": "https://kuan.shangtaika.com/",
                "period_label": "2026",
            }
            rows = _parse_page(source, {"status": 200, "text": SHANGTAIKA_BROADBAND_COMPARISON_2026_TEXT}, "2026-07-06T00:00:00+08:00", "2026")
            self.assertEqual({(row["broadband_speed_mbps"], row["monthly_fee_hkd"]) for row in rows}, expected)
            self.assertTrue(all(row["source_status"] == "public_third_party_comparison_needs_review" for row in rows))
            self.assertTrue(all("Shangtaika" in row["plan_name"] for row in rows))

    def test_parse_smartone_quoquo_2026_broadband_comparison_rows(self) -> None:
        source = {
            "source_id": "smartone_quoquo_broadband_comparison_2026",
            "brand": "SmarTone",
            "product_category": "home_fibre_broadband",
            "url": "https://www.quoquoapp.com/index.php?id=1479&route=module%2Fapp_news1",
            "period_label": "2026",
        }
        rows = _parse_page(source, {"status": 200, "text": QUOQUO_BROADBAND_COMPARISON_2026_TEXT}, "2026-07-07T10:00:00+08:00", "2026")

        self.assertEqual({(row["broadband_speed_mbps"], row["monthly_fee_hkd"]) for row in rows}, {("2200", "128")})
        self.assertEqual({row["contract_months"] for row in rows}, {"36"})
        self.assertTrue(all(row["source_status"] == "public_third_party_comparison_needs_review" for row in rows))
        self.assertTrue(all("5G" not in row["plan_name"] for row in rows))

    def test_parse_hktechreview_broadband_comparison_rows(self) -> None:
        cases = [
            ("hgc_hktechreview_broadband_comparison_2025", "HGC", {"109", "119"}),
            ("hkbn_hktechreview_broadband_comparison_2026", "HKBN", {"88"}),
            ("smartone_hktechreview_broadband_comparison_2026", "SmarTone", {"88"}),
            ("icable_hktechreview_broadband_comparison_2026", "i-CABLE", {"88"}),
        ]
        for source_id, brand, expected_fees in cases:
            source = {
                "source_id": source_id,
                "brand": brand,
                "product_category": "home_fibre_broadband",
                "url": "https://hktechreview.com/broadband-compare/",
            }
            rows = _parse_page(source, {"status": 200, "text": HKTECHREVIEW_BROADBAND_COMPARISON_2025_TEXT}, "2026-07-03T00:00:00+08:00", "2026")
            by_fee = {row["monthly_fee_hkd"]: row for row in rows}

            self.assertEqual(set(by_fee), expected_fees)
            self.assertTrue(all(row["broadband_speed_mbps"] == "1000" for row in rows))
            self.assertTrue(all(row["source_status"] == "public_third_party_comparison_needs_review" for row in rows))
        self.assertEqual(by_fee["88"]["contract_months"], "36")

    def test_parse_hgc_current_fibre_standard_fee_table_only(self) -> None:
        source = {
            "source_id": "hgc_2g_broadband_2023_press",
            "brand": "HGC",
            "product_category": "home_fibre_broadband",
            "url": "https://www.hgcbroadband.com/en/broadband/fibre-to-home",
        }
        rows = _parse_page(source, {"status": 200, "text": HGC_CURRENT_FIBRE_TEXT}, "2026-07-06T00:00:00+08:00", "current")
        by_speed = {row["broadband_speed_mbps"]: row for row in rows}

        self.assertEqual(len(rows), 12)
        self.assertEqual(by_speed["10000"]["monthly_fee_hkd"], "1299")
        self.assertEqual(by_speed["500"]["monthly_fee_hkd"], "488")
        self.assertEqual(by_speed["6"]["monthly_fee_hkd"], "188")
        self.assertFalse({"1500", "680", "150", "500", "10", "200", "50"} & {row["monthly_fee_hkd"] for row in rows})
        self.assertTrue(all(row["tariff_type"] == "monthly_plan_fee" for row in rows))

    def test_parse_hgc_findplanking_2026_offer_listing_rows(self) -> None:
        source = {
            "source_id": "hgc_findplanking_2026_offer_listing",
            "brand": "HGC",
            "product_category": "home_fibre_broadband",
            "url": "https://findplanking.com/broadband/1134",
            "period_label": "2026",
        }
        rows = _parse_page(source, {"status": 200, "text": HGC_FINDPLANKING_2026_TEXT}, "2026-07-06T00:00:00+08:00", "2026")
        speed_fee = {(row["broadband_speed_mbps"], row["monthly_fee_hkd"]) for row in rows}

        self.assertEqual(speed_fee, {("1000", "89"), ("1000", "109"), ("2000", "119"), ("2500", "139")})
        self.assertEqual(len(rows), 4)
        self.assertTrue(all(row["source_status"] == "public_third_party_offer_listing_needs_review" for row in rows))

    def test_parse_hgc_broadband_quote_2026_offer_listing_rows(self) -> None:
        source = {
            "source_id": "hgc_broadband_quote_2026_offer_listing",
            "brand": "HGC",
            "product_category": "home_fibre_broadband",
            "url": "https://www.broadband-quote.com/hgc/hgc%E6%9C%80%E6%96%B0%E5%84%AA%E6%83%A0/",
            "period_label": "2026",
        }
        rows = _parse_page(source, {"status": 200, "text": HGC_BROADBAND_QUOTE_2026_TEXT}, "2026-07-06T00:00:00+08:00", "2026")
        speed_fee = {(row["broadband_speed_mbps"], row["monthly_fee_hkd"]) for row in rows}

        self.assertEqual(speed_fee, {("2000", "119")})
        self.assertEqual(len(rows), 1)
        self.assertTrue(all("非官方" not in row["plan_name"] for row in rows))

    def test_parse_hgc_broadband_pricequote_2500m_category_rows(self) -> None:
        source = {
            "source_id": "hgc_broadband_pricequote_category_2500m_2025",
            "brand": "HGC",
            "product_category": "home_fibre_broadband",
            "url": "https://www.broadband-pricequote.com/broadband-plan/categories/hgc",
            "period_label": "2025",
        }
        rows = _parse_page(source, {"status": 200, "text": HGC_PRICEQUOTE_2500M_CATEGORY_2025_TEXT}, "2026-07-07T00:00:00+08:00", "2025")
        by_fee = {row["monthly_fee_hkd"]: row for row in rows}

        self.assertEqual(set(by_fee), {"139", "159"})
        self.assertEqual(by_fee["139"]["contract_months"], "36")
        self.assertEqual(by_fee["159"]["contract_months"], "24")
        self.assertEqual(by_fee["159"]["source_status"], "public_third_party_offer_listing_needs_review")

    def test_parse_hgc_broadband_pricequote_2000m_x50poe_rows(self) -> None:
        source = {
            "source_id": "hgc_broadband_pricequote_2000m_x50poe_2025",
            "brand": "HGC",
            "product_category": "home_fibre_broadband",
            "url": "https://www.broadband-pricequote.com/post/hgcx50poe-0725",
            "period_label": "2025",
        }
        rows = _parse_page(source, {"status": 200, "text": HGC_PRICEQUOTE_2000M_X50POE_2025_TEXT}, "2026-07-07T00:00:00+08:00", "2025")
        by_fee = {row["monthly_fee_hkd"]: row for row in rows}

        self.assertEqual(set(by_fee), {"189", "199"})
        self.assertEqual(by_fee["189"]["contract_months"], "24")
        self.assertEqual(by_fee["199"]["broadband_speed_mbps"], "2000")
        self.assertEqual(by_fee["199"]["source_status"], "public_third_party_offer_listing_needs_review")

    def test_parse_hgc_broadband_pricequote_2200m_2026_comparison_row(self) -> None:
        source = {
            "source_id": "hgc_broadband_pricequote_2200m_2026",
            "brand": "HGC",
            "product_category": "home_fibre_broadband",
            "url": "https://www.broadband-pricequote.com/post/hgc2200m",
            "period_label": "2026",
        }
        text = (
            "HGC 2200M 家居寬頻優惠。比較表：HGC 2.5G 月費 $139-$149；"
            "HGC 2200M 月費 $129；CMHK 2200M 月費 $168。"
        )
        rows = _parse_page(source, {"status": 200, "text": text}, "2026-07-07T00:00:00+08:00", "2026")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["monthly_fee_hkd"], "149")
        self.assertEqual(rows[0]["broadband_speed_mbps"], "2500")
        self.assertEqual(rows[0]["source_status"], "public_third_party_offer_listing_needs_review")

    def test_parse_3hk_current_skips_admin_fee_noise(self) -> None:
        source = {
            "source_id": "3hk_5g_sim_plan",
            "brand": "3HK / Hutchison",
            "product_category": "mobile_consumer_5g",
            "url": "https://web.three.com.hk/plans/5g/index-en.html",
        }
        rows = _parse_page(source, {"status": 200, "text": THREE_ADMIN_FEE_TEXT}, "2026-07-02T00:00:00+08:00", "current")
        fees = {row["monthly_fee_hkd"] for row in rows}
        self.assertIn("124", fees)
        self.assertNotIn("28", fees)
        self.assertNotIn("18", fees)
        self.assertNotIn("10", fees)

    def test_parse_3hk_current_tc_rows(self) -> None:
        source = {
            "source_id": "3hk_5g_sim_plan_tc",
            "brand": "3HK / Hutchison",
            "product_category": "mobile_consumer_5g",
            "url": "https://web.three.com.hk/plans/5g/index.html",
        }
        rows = _parse_page(source, {"status": 200, "text": THREE_ADMIN_FEE_TC_TEXT}, "2026-07-06T00:00:00+08:00", "current")
        by_name = {row["plan_name"]: row for row in rows}
        self.assertEqual(by_name["3HK 5G Monthly SIM Plan HK$124 30GB"]["average_monthly_fee_hkd"], "100")
        self.assertEqual(by_name["3HK 5G Monthly SIM Plan HK$228 100GB"]["local_data_gb"], "100")
        self.assertEqual(by_name["3HK Chinese Mainland-HK-Macau Shared Data add-on HK$68 10GB"]["roaming_data_gb"], "10")
        self.assertTrue(all(row["monthly_fee_hkd"] != "28" for row in rows))

    def test_parse_3hk_ofca_2012_4g_tariff_revision_rows(self) -> None:
        sources = {
            source["source_id"]: source
            for source in CURRENT_SOURCES
            if source["source_id"] in {
                "3hk_ofca_4g_smartphone_plan_20120503",
                "3hk_ofca_4g_smartphone_plan_20120530",
            }
        }
        self.assertEqual(len(sources), 2)
        original = _parse_page(
            sources["3hk_ofca_4g_smartphone_plan_20120503"],
            {"status": 200, "text": THREE_OFCA_2012_ORIGINAL_TEXT},
            "2026-07-10T00:00:00+08:00",
            "2012",
        )
        revision = _parse_page(
            sources["3hk_ofca_4g_smartphone_plan_20120530"],
            {"status": 200, "text": THREE_OFCA_2012_REVISION_TEXT},
            "2026-07-10T00:00:00+08:00",
            "2012",
        )
        self.assertEqual(len(original), 1)
        self.assertEqual(len(revision), 1)
        self.assertEqual(original[0]["monthly_fee_hkd"], "358")
        self.assertEqual(revision[0]["local_voice"], "3,900 basic mins; 1,600 intra-network mins; 100 video mins")
        self.assertEqual(original[0]["source_status"], "parsed_official_regulatory_pdf_ocr_verified")
        _apply_verification([*original, *revision])
        self.assertEqual(original[0]["verification_count"], "2")
        self.assertEqual(revision[0]["verification_status"], "multi_source_or_multi_snapshot_verified")

    def test_parse_3hk_2014_super_plan_regulatory_and_press_crosscheck(self) -> None:
        sources = {
            source["source_id"]: source
            for source in CURRENT_SOURCES
            if source["source_id"] in {
                "3hk_ofca_smartphone_super_plan_20140211",
                "3hk_jolla_smartphone_super_plan_20140812",
            }
        }
        regulatory = _parse_page(
            sources["3hk_ofca_smartphone_super_plan_20140211"],
            {"status": 200, "text": THREE_OFCA_2014_SUPER_PLAN_TEXT},
            "2026-07-10T00:00:00+08:00",
            "2014",
        )
        press = _parse_page(
            sources["3hk_jolla_smartphone_super_plan_20140812"],
            {"status": 200, "text": THREE_JOLLA_2014_PRESS_TEXT},
            "2026-07-10T00:00:00+08:00",
            "2014",
        )
        self.assertEqual(len(regulatory), 1)
        self.assertEqual(len(press), 1)
        self.assertEqual(regulatory[0]["monthly_fee_hkd"], "168")
        self.assertEqual(regulatory[0]["local_data_gb"], "")
        _apply_verification([*regulatory, *press])
        self.assertTrue(all(row["verification_status"] == "multi_source_or_multi_snapshot_verified" for row in [*regulatory, *press]))

    def test_parse_3hk_2018_greater_china_plan_official_and_media_crosscheck(self) -> None:
        sources = {
            source["source_id"]: source
            for source in CURRENT_SOURCES
            if source["source_id"] in {
                "3hk_greater_china_plan_20180720_official_pdf",
                "3hk_greater_china_plan_20180720_qooah",
            }
        }
        self.assertEqual(len(sources), 2)
        official = _parse_page(
            sources["3hk_greater_china_plan_20180720_official_pdf"],
            {"status": 200, "text": THREE_GREATER_CHINA_PLAN_2018_OFFICIAL_TEXT},
            "2026-07-10T00:00:00+08:00",
            "2018",
        )
        media = _parse_page(
            sources["3hk_greater_china_plan_20180720_qooah"],
            {"status": 200, "text": THREE_GREATER_CHINA_PLAN_2018_QOOAH_TEXT},
            "2026-07-10T00:00:00+08:00",
            "2018",
        )
        self.assertEqual([(row["monthly_fee_hkd"], row["local_data_gb"]) for row in official], [("188", "4"), ("238", "8"), ("328", "12")])
        self.assertEqual([(row["monthly_fee_hkd"], row["local_data_gb"]) for row in media], [("188", "4"), ("238", "8"), ("328", "12")])
        self.assertTrue(all(row["contract_months"] == "24" for row in official))
        self.assertTrue(all(not row["contract_months"] for row in media))
        _apply_verification([*official, *media])
        self.assertTrue(all(row["verification_count"] == "2" for row in [*official, *media]))
        self.assertTrue(all(row["verification_status"] == "multi_source_or_multi_snapshot_verified" for row in [*official, *media]))

    def test_parse_3hk_2015_whatsapp_premium_official_crosscheck(self) -> None:
        sources = {
            source["source_id"]: source
            for source in CURRENT_SOURCES
            if source["source_id"] in {
                "3hk_whatsapp_premium_20150506_group_press",
                "3hk_whatsapp_premium_20150506_product_pdf",
            }
        }
        self.assertEqual(len(sources), 2)
        group_press = _parse_page(
            sources["3hk_whatsapp_premium_20150506_group_press"],
            {"status": 200, "text": THREE_WHATSAPP_PREMIUM_2015_TEXT},
            "2026-07-10T00:00:00+08:00",
            "2015",
        )
        product_pdf = _parse_page(
            sources["3hk_whatsapp_premium_20150506_product_pdf"],
            {"status": 200, "text": THREE_WHATSAPP_PREMIUM_2015_TEXT},
            "2026-07-10T00:00:00+08:00",
            "2015",
        )
        self.assertEqual(
            [(row["monthly_fee_hkd"], row["tariff_type"]) for row in group_press],
            [("18", "monthly_plan_fee"), ("48", "daily_pass_fee")],
        )
        _apply_verification([*group_press, *product_pdf])
        self.assertTrue(all(row["verification_count"] == "2" for row in [*group_press, *product_pdf]))
        self.assertTrue(all(row["verification_status"] == "multi_source_or_multi_snapshot_verified" for row in [*group_press, *product_pdf]))

    def test_parse_3hk_2017_3gamer_bilingual_official_crosscheck(self) -> None:
        sources = {
            source["source_id"]: source
            for source in CURRENT_SOURCES
            if source["source_id"] in {
                "3hk_3gamer_20171207_en_official_press",
                "3hk_3gamer_20171207_tc_official_press",
            }
        }
        self.assertEqual(len(sources), 2)
        english = _parse_page(
            sources["3hk_3gamer_20171207_en_official_press"],
            {"status": 200, "text": THREE_3GAMER_2017_EN_TEXT},
            "2026-07-10T00:00:00+08:00",
            "2017",
        )
        chinese = _parse_page(
            sources["3hk_3gamer_20171207_tc_official_press"],
            {"status": 200, "text": THREE_3GAMER_2017_TC_TEXT},
            "2026-07-10T00:00:00+08:00",
            "2017",
        )
        self.assertEqual(
            [(row["monthly_fee_hkd"], row["local_data_gb"], row["contract_months"]) for row in english],
            [("218", "5", "24"), ("48", "", "")],
        )
        _apply_verification([*english, *chinese])
        self.assertTrue(all(row["verification_count"] == "2" for row in [*english, *chinese]))
        self.assertTrue(all(row["verification_status"] == "multi_source_or_multi_snapshot_verified" for row in [*english, *chinese]))

    def test_parse_3hk_2013_ipair_bilingual_official_crosscheck(self) -> None:
        sources = {
            source["source_id"]: source
            for source in CURRENT_SOURCES
            if source["source_id"] in {
                "3hk_ipair_20131127_en_official_press",
                "3hk_ipair_20131127_tc_official_press",
            }
        }
        self.assertEqual(len(sources), 2)
        english_text = "3 Hong Kong customers can enjoy i-Pair service for the lowest price worldwide - just $28 a month. Customers can subscribe to a $49 monthly plan with additional upgraded service for the first month."
        chinese_text = "3 香港客戶獨享全球最低的《愛情公寓》$28 月費優惠。3 香港客戶亦可以$49 月費獨立申請成為白金會員，於首月額外獲贈指定升級服務。"
        english = _parse_page(sources["3hk_ipair_20131127_en_official_press"], {"status": 200, "text": english_text}, "2026-07-10T00:00:00+08:00", "2013")
        chinese = _parse_page(sources["3hk_ipair_20131127_tc_official_press"], {"status": 200, "text": chinese_text}, "2026-07-10T00:00:00+08:00", "2013")
        self.assertEqual([row["monthly_fee_hkd"] for row in english], ["28", "49"])
        _apply_verification([*english, *chinese])
        self.assertTrue(all(row["verification_count"] == "2" for row in [*english, *chinese]))
        self.assertTrue(all(row["verification_status"] == "multi_source_or_multi_snapshot_verified" for row in [*english, *chinese]))

    def test_parse_3hk_2011_smart_unlimited_bilingual_official_crosscheck(self) -> None:
        sources = {
            source["source_id"]: source
            for source in CURRENT_SOURCES
            if source["source_id"] in {
                "3hk_samsung_galaxy_s2_20110610_en_official_press",
                "3hk_samsung_galaxy_s2_20110610_tc_official_press",
            }
        }
        self.assertEqual(len(sources), 2)
        english_text = "Customers that choose the HK$148 Smart Unlimited Monthly Plan can get the Samsung GALAXY S II as part of a $0 handset price subscription offer."
        chinese_text = "客戶只需選用$148「無限 Smart」月費計劃，即可以$0 機價選購 Samsung GALAXY S II。"
        english = _parse_page(sources["3hk_samsung_galaxy_s2_20110610_en_official_press"], {"status": 200, "text": english_text}, "2026-07-10T00:00:00+08:00", "2011")
        chinese = _parse_page(sources["3hk_samsung_galaxy_s2_20110610_tc_official_press"], {"status": 200, "text": chinese_text}, "2026-07-10T00:00:00+08:00", "2011")
        self.assertEqual([(row["monthly_fee_hkd"], row["local_data_gb"], row["contract_months"]) for row in english], [("148", "", "")])
        _apply_verification([*english, *chinese])
        self.assertTrue(all(row["verification_count"] == "2" for row in [*english, *chinese]))
        self.assertTrue(all(row["verification_status"] == "multi_source_or_multi_snapshot_verified" for row in [*english, *chinese]))

    def test_parse_3hk_2011_anyplex_bilingual_official_crosscheck(self) -> None:
        sources = {source["source_id"]: source for source in CURRENT_SOURCES if source["source_id"] in {"3hk_anyplex_htc_20111101_en_official_press", "3hk_anyplex_htc_20111101_tc_official_press"}}
        self.assertEqual(len(sources), 2)
        english = _parse_page(sources["3hk_anyplex_htc_20111101_en_official_press"], {"status": 200, "text": "Anyplex App is offered at $49 a month. Customers who subscribe to the $298 \"Smart Unlimited\" monthly plan receive 2,500 basic airtime minutes and 800MB local wireless data."}, "2026-07-10T00:00:00+08:00", "2011")
        chinese = _parse_page(sources["3hk_anyplex_htc_20111101_tc_official_press"], {"status": 200, "text": "Anyplex 每月$49 任睇近200套猛片。客戶選用$298的無限Smart月費計劃，可享2,500分鐘通話時間、800MB本地數據。"}, "2026-07-10T00:00:00+08:00", "2011")
        self.assertEqual([(row["monthly_fee_hkd"], row["local_data_gb"]) for row in english], [("49", ""), ("298", "0.8")])
        _apply_verification([*english, *chinese])
        self.assertTrue(all(row["verification_count"] == "2" for row in [*english, *chinese]))
        self.assertTrue(all(row["verification_status"] == "multi_source_or_multi_snapshot_verified" for row in [*english, *chinese]))

    def test_parse_3home_2016_entertainment_super_pack_official_crosscheck(self) -> None:
        sources = {
            source["source_id"]: source
            for source in CURRENT_SOURCES
            if source["source_id"] in {
                "3home_entertainment_super_pack_20160427_group_press",
                "3home_entertainment_super_pack_20160427_product_pdf",
            }
        }
        self.assertEqual(len(sources), 2)
        group_press = _parse_page(
            sources["3home_entertainment_super_pack_20160427_group_press"],
            {"status": 200, "text": THREE_HOME_ENTERTAINMENT_2016_TEXT},
            "2026-07-10T00:00:00+08:00",
            "2016",
        )
        product_pdf = _parse_page(
            sources["3home_entertainment_super_pack_20160427_product_pdf"],
            {"status": 200, "text": THREE_HOME_ENTERTAINMENT_2016_TEXT},
            "2026-07-10T00:00:00+08:00",
            "2016",
        )
        self.assertEqual(
            [(row["monthly_fee_hkd"], row["broadband_speed_mbps"], row["contract_months"]) for row in group_press],
            [("138", "100", "24"), ("188", "1000", "24")],
        )
        _apply_verification([*group_press, *product_pdf])
        self.assertTrue(all(row["verification_count"] == "2" for row in [*group_press, *product_pdf]))
        self.assertTrue(all(row["verification_status"] == "multi_source_or_multi_snapshot_verified" for row in [*group_press, *product_pdf]))

    def test_parse_3ree_broadband_2010_bilingual_official_crosscheck(self) -> None:
        sources = {
            source["source_id"]: source
            for source in CURRENT_SOURCES
            if source["source_id"] in {
                "3hk_3ree_broadband_20100722_en_official_press",
                "3hk_3ree_broadband_20100722_tc_official_press",
            }
        }
        self.assertEqual(len(sources), 2)
        english = _parse_page(
            sources["3hk_3ree_broadband_20100722_en_official_press"],
            {"status": 200, "text": THREE_3REE_BROADBAND_2010_EN_TEXT},
            "2026-07-10T00:00:00+08:00",
            "2010",
        )
        chinese = _parse_page(
            sources["3hk_3ree_broadband_20100722_tc_official_press"],
            {"status": 200, "text": THREE_3REE_BROADBAND_2010_TC_TEXT},
            "2026-07-10T00:00:00+08:00",
            "2010",
        )
        self.assertEqual([(row["monthly_fee_hkd"], row["broadband_speed_mbps"]) for row in english], [("99", "100")])
        _apply_verification([*english, *chinese])
        self.assertTrue(all(row["verification_count"] == "2" for row in [*english, *chinese]))
        self.assertTrue(all(row["verification_status"] == "multi_source_or_multi_snapshot_verified" for row in [*english, *chinese]))

    def test_parse_3hk_historical_tc_archive_rows(self) -> None:
        source = {
            "source_id": "3hk_5g_sim_plan_tc",
            "brand": "3HK / Hutchison",
            "product_category": "mobile_consumer_5g",
            "url": "https://web.three.com.hk/plans/5g/index.html",
        }
        text = (
            "5G轉台免行政費 5G SIM 月費計劃 步驟1: 揀選計劃 "
            "入門首選 基本月費 1 $ 124 本地數據 ∆ 30 GB 其後任用 ▲ (高達1Mbps) "
            "5G SIM 月費計劃 本地數據30GB 3,000本地通話分鐘 24個月合約 "
            "基本月費 1 $ 148 本地數據 ∆ 50 GB 其後任用 ▲ (高達1Mbps) "
            "5G SIM 月費計劃 送3GB內地及澳門數據 ∆ 本地數據50GB 3,000本地通話分鐘 24個月合約 "
            "平均月費 2 $ 168 $188 本地數據 ∆ 60 GB 其後任用 ▲ (高達1Mbps) "
            "5G SIM 月費計劃 送1GB內地及澳門數據 ∆ 本地數據60GB 3,000本地通話分鐘 28個月合約 "
            "其後本地服務及其他收費 行政費 $28/月 通話分鐘及短訊 "
            "內地及港澳共享數據增值 + $68/10GB 或 $128/20GB"
        )
        rows = _parse_page(
            source,
            {"status": 200, "text": text},
            "2026-07-08T00:00:00+08:00",
            "2024",
            "http://web.archive.org/web/20240526221942/https://web.three.com.hk/plans/5g/index.html",
        )
        fee_data = {(row["monthly_fee_hkd"], row["local_data_gb"]) for row in rows}

        self.assertEqual(fee_data, {("124", "30"), ("148", "50"), ("188", "60")})
        self.assertEqual({row["source_status"] for row in rows}, {"parsed_archive"})
        self.assertEqual(next(row for row in rows if row["monthly_fee_hkd"] == "188")["average_monthly_fee_hkd"], "168")
        self.assertTrue(all(row["monthly_fee_hkd"] not in {"28", "68", "128"} for row in rows))

    def test_parse_3hk_historical_en_archive_rows(self) -> None:
        source = {
            "source_id": "3hk_5g_sim_plan",
            "brand": "3HK / Hutchison",
            "product_category": "mobile_consumer_5g",
            "url": "https://web.three.com.hk/plans/5g/index-en.html",
        }
        text = (
            "5G SIM Monthly Plan Step 1: Choose a plan "
            "For 5G Starters Monthly fee 1 $ 124 Local data ∆ 30 GB Thereafter Infinite Data ▲ (Up to 1Mbps) "
            "5G Monthly SIM Plan Local data 30GB 3,000 local voice minutes 24-month Contract "
            "Monthly fee 1 $ 148 Local data ∆ 50 GB Thereafter Infinite Data ▲ (Up to 1Mbps) "
            "5G Monthly SIM Plan FREE 3GB mainland China-Macau shared data ∆ Local data 50GB 3,000 local voice minutes 24-month Contract "
            "Average Monthly Fee 2 $ 168 $188 Local data ∆ 60 GB Thereafter Infinite Data ▲ (Up to 1Mbps) "
            "5G Monthly SIM Plan FREE 1GB mainland China-Macau shared data ∆ Local data 60GB 3,000 local voice minutes 28-month Contract "
            "Other Local and Thereafter Charge Admin Fee $28/month "
            "Mainland China-HK-Macau shared data add-on + $68/10GB or $128/20GB"
        )
        rows = _parse_page(
            source,
            {"status": 200, "text": text},
            "2026-07-08T00:00:00+08:00",
            "2024",
            "http://web.archive.org/web/20240526212216/https://web.three.com.hk/plans/5g/index-en.html",
        )
        fee_data = {(row["monthly_fee_hkd"], row["local_data_gb"]) for row in rows}

        self.assertEqual(fee_data, {("124", "30"), ("148", "50"), ("188", "60")})
        self.assertEqual({row["source_status"] for row in rows}, {"parsed_archive"})
        self.assertEqual(next(row for row in rows if row["monthly_fee_hkd"] == "188")["contract_months"], "28")
        self.assertEqual(next(row for row in rows if row["monthly_fee_hkd"] == "188")["average_monthly_fee_hkd"], "168")
        self.assertTrue(all(row["monthly_fee_hkd"] not in {"28", "68", "128"} for row in rows))

    def test_parse_3hk_business_tc_keeps_main_plan_fees_only(self) -> None:
        source = {
            "source_id": "3hk_business_5g_tc",
            "brand": "3HK / Hutchison",
            "product_category": "business_mobile_5g",
            "url": "https://web.three.com.hk/plans/3business5g/index.html",
        }
        rows = _parse_page(source, {"status": 200, "text": THREE_BUSINESS_5G_TC_TEXT}, "2026-07-06T00:00:00+08:00", "current")
        fee_data = {(row["monthly_fee_hkd"], row["local_data_gb"]) for row in rows}

        self.assertEqual(fee_data, {("124", "30"), ("188", "60")})
        self.assertTrue(all(row["monthly_fee_hkd"] not in {"28", "30", "388"} for row in rows))

    def test_parse_3hk_sosim_tc_rows(self) -> None:
        source = {
            "source_id": "3hk_sosim_local_tc",
            "brand": "3HK / Hutchison",
            "product_category": "prepaid_mobile",
            "url": "https://www.sosimhk.com/tc/local/data-service.html",
        }
        rows = _parse_page(source, {"status": 200, "text": THREE_SOSIM_TC_TEXT}, "2026-07-06T00:00:00+08:00", "current")
        by_fee = {row["monthly_fee_hkd"]: row for row in rows}

        self.assertEqual(set(by_fee), {"33", "48"})
        self.assertEqual(by_fee["48"]["local_data_gb"], "60")

    def test_parse_3hk_world_plan_current_rows_do_not_shift_data(self) -> None:
        source = {
            "source_id": "3hk_world_plan",
            "brand": "3HK / Hutchison",
            "product_category": "mobile_consumer_roaming",
            "url": "https://web.three.com.hk/3hkworld/index-en.html",
        }
        rows = _parse_page(source, {"status": 200, "text": THREE_WORLD_PLAN_TEXT}, "2026-07-06T00:00:00+08:00", "current")
        by_fee = {row["monthly_fee_hkd"]: row for row in rows}
        self.assertEqual(len(rows), 7)
        self.assertEqual(by_fee["198"]["local_data_gb"], "10")
        self.assertEqual(by_fee["268"]["local_data_gb"], "20")
        self.assertEqual(by_fee["958"]["local_data_gb"], "200")
        self.assertTrue(all(row["tariff_type"] == "monthly_plan_fee" for row in rows))

    def test_parse_3hk_world_plan_tc_crosscheck_rows(self) -> None:
        source = {
            "source_id": "3hk_world_plan_tc",
            "brand": "3HK / Hutchison",
            "product_category": "mobile_consumer_roaming",
            "url": "https://web.three.com.hk/3hkworld/index.html",
        }
        rows = _parse_page(source, {"status": 200, "text": THREE_WORLD_PLAN_TC_TEXT}, "2026-07-06T00:00:00+08:00", "current")
        by_fee = {row["monthly_fee_hkd"]: row for row in rows}
        self.assertEqual(len(rows), 7)
        self.assertEqual(by_fee["198"]["plan_name"], "3HK World Plan HK$198 10GB")
        self.assertEqual(by_fee["728"]["roaming_data_gb"], "100")

    def test_parse_3hk_world_plan_alt_current_rows(self) -> None:
        source = {
            "source_id": "3hk_world_plan_alt",
            "brand": "3HK / Hutchison",
            "product_category": "mobile_consumer_roaming",
            "url": "https://web.three.com.hk/3hkworld/index2-en.html",
        }
        rows = _parse_page(source, {"status": 200, "text": THREE_WORLD_PLAN_ALT_TEXT}, "2026-07-06T00:00:00+08:00", "current")
        by_fee = {row["monthly_fee_hkd"]: row for row in rows}
        self.assertEqual(len(rows), 7)
        self.assertEqual(by_fee["158"]["local_data_gb"], "10")
        self.assertEqual(by_fee["798"]["local_data_gb"], "200")

    def test_parse_3hk_2024_official_pdf_rows(self) -> None:
        source = {
            "source_id": "3hk_promo5g_2024_pdf",
            "brand": "3HK / Hutchison",
            "product_category": "mobile_consumer_5g",
            "url": "https://web.three.com.hk/tnc/240625/tnc-promo5g-en.pdf",
            "period_label": "2024",
        }
        rows = _parse_page(source, {"status": 200, "text": THREE_PROMO_2024_TEXT}, "2026-07-02T00:00:00+08:00", "2024")
        by_fee = {row["monthly_fee_hkd"]: row for row in rows}
        self.assertEqual(set(by_fee), {"124", "148", "188"})
        self.assertEqual(by_fee["124"]["local_data_gb"], "30")
        self.assertEqual(by_fee["148"]["local_data_gb"], "50")
        self.assertEqual(by_fee["188"]["local_data_gb"], "60")
        self.assertEqual(by_fee["188"]["contract_months"], "28")
        self.assertEqual(by_fee["124"]["add_on_charges_hkd"], "28 admin fee per month")
        self.assertTrue(all(row["source_status"] == "parsed_public_official_pdf" for row in rows))

    def test_parse_3hk_2025_public_product_guide_rows(self) -> None:
        source = {
            "source_id": "3hk_extrabux_2025_product_guide",
            "brand": "3HK / Hutchison",
            "product_category": "mobile_consumer_5g",
            "url": "https://www.extrabux.com/chs/guide/8516563",
            "period_label": "2025",
        }
        rows = _parse_page(source, {"status": 200, "text": THREE_EXTRABUX_2025_TEXT}, "2026-07-03T00:00:00+08:00", "2025")
        by_fee = {row["monthly_fee_hkd"]: row for row in rows}
        self.assertEqual(set(by_fee), {"124", "148", "168"})
        self.assertEqual(by_fee["124"]["local_data_gb"], "30")
        self.assertEqual(by_fee["148"]["roaming_data_gb"], "3")
        self.assertEqual(by_fee["168"]["contract_months"], "28")
        self.assertTrue(all(row["source_status"] == "public_third_party_product_guide_needs_review" for row in rows))

    def test_parse_3hk_2025_thriftyhk_mobile_comparison_row(self) -> None:
        source = {
            "source_id": "3hk_thriftyhk_2025_mobile_plan_comparison",
            "brand": "3HK / Hutchison",
            "product_category": "mobile_consumer_5g",
            "url": "https://www.thriftyhk.com/post/best-5g-mobile-plan-hongkong",
            "period_label": "2025",
        }
        rows = _parse_page(source, {"status": 200, "text": THREE_THRIFTYHK_2025_TEXT}, "2026-07-03T00:00:00+08:00", "2025")
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["monthly_fee_hkd"], "168")
        self.assertEqual(row["local_data_gb"], "60")
        self.assertEqual(row["local_voice"], "3000 local voice minutes")
        self.assertIn("HK$30/5GB", row["add_on_charges_hkd"])
        self.assertEqual(row["source_status"], "public_third_party_mobile_plan_comparison_needs_review")

    def test_parse_smartone_current_5g_detail_row(self) -> None:
        source = {
            "source_id": "smartone_5g_110g_30m_239_current",
            "brand": "SmarTone",
            "product_category": "mobile_consumer_5g",
            "url": "https://www.smartone.com/en/home/mobile-service-plans/5G-listing/detail/?group=5g_travel&plan=5g_110g_30m_239_travel",
        }
        rows = _parse_page(source, {"status": 200, "text": SMARTONE_5G_TRAVEL_110G_DETAIL_TEXT}, "2026-07-06T00:00:00+08:00", "current")
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["monthly_fee_hkd"], "239")
        self.assertEqual(row["local_data_gb"], "110")
        self.assertEqual(row["contract_months"], "30")
        self.assertEqual(row["local_voice"], "unlimited local voice minutes")
        self.assertIn("HK$18 admin fee", row["add_on_charges_hkd"])
        self.assertEqual(row["source_status"], "parsed_current")

    def test_parse_smartone_5g_listing_main_plan_blocks(self) -> None:
        source = {
            "source_id": "smartone_5g_listing",
            "brand": "SmarTone",
            "product_category": "mobile_consumer_5g",
            "url": "https://www.smartone.com/en/home/mobile-service-plans/5G-listing/",
        }
        rows = _parse_page(source, {"status": 200, "text": SMARTONE_5G_LISTING_TEXT}, "2026-07-06T00:00:00+08:00", "current")
        by_fee = {row["monthly_fee_hkd"]: row for row in rows}
        self.assertEqual(len(rows), 2)
        self.assertEqual(by_fee["299"]["local_data_gb"], "110")
        self.assertEqual(by_fee["299"]["contract_months"], "24")
        self.assertEqual(by_fee["179"]["local_data_gb"], "50")
        self.assertNotIn("28", by_fee)
        self.assertNotIn("1500", by_fee)
        self.assertNotIn("500", by_fee)

    def test_parse_smartone_5g_listing_tc_main_plan_blocks(self) -> None:
        source = {
            "source_id": "smartone_5g_listing_tc",
            "brand": "SmarTone",
            "product_category": "mobile_consumer_5g",
            "url": "https://www.smartone.com/tc/home/mobile-service-plans/5G-listing/",
        }
        rows = _parse_page(source, {"status": 200, "text": SMARTONE_5G_LISTING_TC_TEXT}, "2026-07-06T00:00:00+08:00", "current")
        by_fee = {row["monthly_fee_hkd"]: row for row in rows}
        self.assertEqual(len(rows), 2)
        self.assertEqual(by_fee["299"]["local_data_gb"], "110")
        self.assertEqual(by_fee["299"]["contract_months"], "24")
        self.assertEqual(by_fee["179"]["local_data_gb"], "50")
        self.assertNotIn("28", by_fee)
        self.assertNotIn("1500", by_fee)
        self.assertNotIn("500", by_fee)

    def test_parse_smartone_subscription_offers_does_not_emit_nav_prices(self) -> None:
        source = {
            "source_id": "smartone_subscription_offers",
            "brand": "SmarTone",
            "product_category": "mobile_consumer_5g",
            "url": "https://www.smartone.com/en/mobile_and_price_plans/subscription-offers/",
        }
        rows = _parse_page(source, {"status": 200, "text": SMARTONE_SUBSCRIPTION_OFFERS_NAV_TEXT}, "2026-07-06T00:00:00+08:00", "current")
        self.assertEqual(rows, [])

    def test_parse_smartone_subscription_offers_plan_rows(self) -> None:
        source = {
            "source_id": "smartone_subscription_offers",
            "brand": "SmarTone",
            "product_category": "mobile_consumer_5g",
            "url": "https://www.smartone.com/en/mobile_and_price_plans/subscription-offers/",
        }
        rows = _parse_page(source, {"status": 200, "text": SMARTONE_SUBSCRIPTION_OFFERS_PLAN_TEXT}, "2026-07-06T00:00:00+08:00", "current")
        by_fee = {row["monthly_fee_hkd"]: row for row in rows}
        self.assertEqual(set(by_fee), {"179", "239", "299"})
        self.assertEqual(by_fee["179"]["local_data_gb"], "50")
        self.assertEqual(by_fee["239"]["local_data_gb"], "110")
        self.assertEqual(by_fee["299"]["contract_months"], "24")
        self.assertTrue(all(row["source_status"] == "parsed_current_official_offer_page" for row in rows))
        self.assertNotIn("41", by_fee)
        self.assertNotIn("88", by_fee)
        self.assertNotIn("81", by_fee)

    def test_parse_smartone_moneysmart_2026_mobile_comparison_row(self) -> None:
        source = {
            "source_id": "smartone_moneysmart_2026_mobile_plan_comparison",
            "brand": "SmarTone",
            "product_category": "mobile_consumer_5g",
            "url": "https://blog.moneysmart.hk/zh-hk/budgeting/mobile-plan",
            "period_label": "2026",
        }
        rows = _parse_page(source, {"status": 200, "text": SMARTONE_MONEYSMART_2026_TEXT}, "2026-07-06T00:00:00+08:00", "2026")
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["monthly_fee_hkd"], "299")
        self.assertEqual(row["local_data_gb"], "110")
        self.assertEqual(row["roaming_data_gb"], "35")
        self.assertEqual(row["contract_months"], "24")
        self.assertEqual(row["source_status"], "public_third_party_mobile_plan_comparison_needs_review")
        self.assertIn("HK$239/110GB 合约期与 SmarTone 官方详情页存在差异", row["evidence_excerpt"])

    def test_parse_smartone_quoquo_2026_mobile_comparison_row(self) -> None:
        source = {
            "source_id": "smartone_quoquo_2026_mobile_plan_comparison",
            "brand": "SmarTone",
            "product_category": "mobile_consumer_5g",
            "url": "https://www.quoquoapp.com/index.php?id=1493&route=module%2Fapp_news1",
            "period_label": "2026",
        }
        text = (
            "5G上台月費比較5/2026 - QuoQuoApp 報價鴨. "
            "比較6間供應商嘅5G計劃，包括CSL、SmarTone、3HK、中移動。 "
            "SmarTone row includes: $129 / 30GB, admin fee waived, 30-month contract, "
            "2GB Mainland China + Macau data. "
            "Another sales note mentions $149 / 20GB and unrelated vouchers."
        )
        rows = _parse_page(source, {"status": 200, "text": text}, "2026-07-08T00:00:00+08:00", "2026")
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["monthly_fee_hkd"], "129")
        self.assertEqual(row["local_data_gb"], "30")
        self.assertEqual(row["roaming_data_gb"], "2")
        self.assertEqual(row["contract_months"], "30")
        self.assertEqual(row["source_status"], "public_third_party_mobile_plan_comparison_needs_review")
        self.assertNotIn("149", row["monthly_fee_hkd"])

    def test_parse_smartone_home_5g_current_shell_excerpt(self) -> None:
        source = {
            "source_id": "smartone_home_5g_broadband",
            "brand": "SmarTone",
            "product_category": "home_5g_broadband",
            "url": "https://www.smartone.com/en/Home5GBroadband/",
        }
        rows = _parse_page(source, {"status": 200, "text": SMARTONE_HOME_5G_CURRENT_TEXT}, "2026-07-07T00:00:00+08:00", "current")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["monthly_fee_hkd"], "178")
        self.assertEqual(rows[0]["contract_months"], "")
        self.assertEqual(rows[0]["local_data_gb"], "")
        self.assertEqual(rows[0]["source_status"], "parsed_current_official_offer_page")

    def test_parse_smartone_home_5g_flexi_combo_crosscheck_excerpt(self) -> None:
        source = {
            "source_id": "smartone_home_5g_flexi_combo_current",
            "brand": "SmarTone",
            "product_category": "home_5g_broadband",
            "url": "https://www.smartone.com/en/mobile_and_price_plans/offer_detail/11-flexi-combo/4483/",
        }
        rows = _parse_page(source, {"status": 200, "text": SMARTONE_HOME_5G_CURRENT_TEXT}, "2026-07-07T00:00:00+08:00", "current")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["plan_name"], "SmarTone Home 5G Broadband Online Exclusive HK$178")
        self.assertEqual(rows[0]["monthly_fee_hkd"], "178")
        self.assertEqual(rows[0]["source_status"], "parsed_current_official_offer_page")

    def test_parse_icable_service_charge_pdf_only_keeps_broadband_rates(self) -> None:
        source = {
            "source_id": "icable_residential_service_charge_2023_pdf",
            "brand": "i-CABLE",
            "product_category": "home_fibre_broadband",
            "url": "https://apps5.i-cable.com/dl/editor/6540c75c357d5.pdf",
            "period_label": "2023",
        }
        rows = _parse_page(source, {"status": 200, "text": ICABLE_SERVICE_CHARGE_TEXT}, "2026-07-02T00:00:00+08:00", "2023")
        by_speed = {row["broadband_speed_mbps"]: row for row in rows}
        self.assertEqual(set(by_speed), {"100", "200", "500", "1000", "2000"})
        self.assertEqual(by_speed["1000"]["monthly_fee_hkd"], "569")
        self.assertEqual(by_speed["2000"]["monthly_fee_hkd"], "669")
        self.assertTrue(all(row["source_status"] == "parsed_public_official_pdf" for row in rows))
        self.assertFalse(any(row["monthly_fee_hkd"] in {"79", "198", "199"} for row in rows))

    def test_parse_icable_home_broadband_service_tc_current_page(self) -> None:
        source = {
            "source_id": "icable_home_broadband_service_tc",
            "brand": "i-CABLE",
            "product_category": "home_fibre_broadband",
            "url": "https://service.i-cable.com/tc/homebroadband",
        }
        rows = _parse_page(source, {"status": 200, "text": ICABLE_HOME_BROADBAND_SERVICE_TC_TEXT}, "2026-07-07T00:00:00+08:00", "current")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["plan_name"], "i-CABLE Home Broadband 2000M HK$118")
        self.assertEqual(rows[0]["monthly_fee_hkd"], "118")
        self.assertEqual(rows[0]["broadband_speed_mbps"], "2000")
        self.assertEqual(rows[0]["source_status"], "parsed_current_official_page")

    def test_parse_icable_current_offer_keeps_1000m_88_contract(self) -> None:
        source = {
            "source_id": "icable_broadband_offer",
            "brand": "i-CABLE",
            "product_category": "home_fibre_broadband",
            "url": "https://www.i-cablebroadband-offer.com/",
        }
        rows = _parse_page(source, {"status": 200, "text": ICABLE_BROADBAND_OFFER_CURRENT_TEXT}, "2026-07-08T00:00:00+08:00", "current")
        private_88 = [row for row in rows if row["monthly_fee_hkd"] == "88" and row["broadband_speed_mbps"] == "1000"]
        self.assertEqual(len(private_88), 1)
        self.assertEqual(private_88[0]["contract_months"], "36")
        self.assertEqual(private_88[0]["source_status"], "public_channel_offer_needs_review")

    def test_parse_icable_mytv_bundle_2021_press_row(self) -> None:
        source = {
            "source_id": "icable_mytv_bundle_2021_tvb_press",
            "brand": "i-CABLE",
            "product_category": "home_fibre_broadband",
            "url": "https://corporate.tvb.com/article/799a5b7839f606a43d71c42f096e50e7.html",
            "period_label": "2021",
        }
        rows = _parse_page(source, {"status": 200, "text": ICABLE_MYTV_BUNDLE_2021_TEXT}, "2026-07-03T00:00:00+08:00", "2021")
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["monthly_fee_hkd"], "198")
        self.assertEqual(row["broadband_speed_mbps"], "1000")
        self.assertEqual(row["contract_months"], "24")
        self.assertEqual(row["source_status"], "public_partner_press_release_needs_review")

    def test_parse_icable_mytv_2021_mytvsuper_service_fee_row(self) -> None:
        source = {
            "source_id": "icable_mytv_2021_mytvsuper_service_fee",
            "brand": "i-CABLE",
            "product_category": "home_fibre_broadband",
            "url": "https://promo.mytvsuper.com/en/service-fee/i-cable",
            "period_label": "2021",
        }
        rows = _parse_page(source, {"status": 200, "text": ICABLE_MYTV_SERVICE_FEE_2021_TEXT}, "2026-07-03T00:00:00+08:00", "2021")
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["plan_name"], "i-CABLE 1G Home Broadband plus myTV Gold bundle HK$198")
        self.assertEqual(row["monthly_fee_hkd"], "198")
        self.assertEqual(row["broadband_speed_mbps"], "1000")
        self.assertEqual(row["contract_months"], "24")
        self.assertEqual(row["source_status"], "public_partner_service_fee_needs_review")

    def test_parse_icable_findplanking_2026_public_housing_75_only(self) -> None:
        source = {
            "source_id": "icable_findplanking_2026_public_housing_75",
            "brand": "i-CABLE",
            "product_category": "home_fibre_broadband",
            "url": "https://findplanking.com/broadband/1214",
            "period_label": "2026",
        }
        rows = _parse_page(source, {"status": 200, "text": ICABLE_FINDPLANKING_2026_PUBLIC_HOUSING_75_TEXT}, "2026-07-06T00:00:00+08:00", "2026")
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["plan_name"], "i-CABLE Broadband 公屋居屋 1000M HK$75")
        self.assertEqual(row["monthly_fee_hkd"], "75")
        self.assertEqual(row["broadband_speed_mbps"], "1000")
        self.assertIn("router included", row["add_on_charges_hkd"])
        self.assertEqual(row["source_status"], "public_third_party_offer_listing_needs_review")

    def test_parse_hgc_mytv_2025_public_offer_rows(self) -> None:
        cases = [
            (
                "hgc_mytv_2025_broadband_pricequote",
                "https://www.broadband-pricequote.com/post/%E3%80%90hgc%E5%85%89%E7%BA%8E%E5%AF%9B%E9%A0%BB%E9%80%A3mytv-gold%E3%80%91%E6%9C%88%E8%B2%BB-%EF%BC%91%EF%BC%99%EF%BC%98-%E3%80%90mytv-super%E5%9F%BA%E6%9C%AC%E7%89%88%E3%80%91%E6%9C%88%E8%B2%BB-%EF%BC%91%EF%BC%90%EF%BC%99",
                HGC_MYTV_PRICEQUOTE_2025_TEXT,
            ),
            (
                "hgc_mytv_2025_broadband_pricequote_post",
                "https://www.broadband-pricequote.com/posts/%E3%80%90hgc%E5%85%89%E7%BA%8E%E5%AF%9B%E9%A0%BB%E9%80%A3mytv-gold%E3%80%91%E6%9C%88%E8%B2%BB%EF%B9%A9%EF%BC%91%EF%BC%99%EF%BC%98%2F%E3%80%90mytv-super%E5%9F%BA%E6%9C%AC%E7%89%88%E3%80%91%E6%9C%88%E8%B2%BB%EF%B9%A9%EF%BC%91%EF%BC%90%EF%BC%99",
                HGC_MYTV_PRICEQUOTE_POST_2025_TEXT,
            ),
        ]
        for source_id, url, text in cases:
            source = {
                "source_id": source_id,
                "brand": "HGC",
                "product_category": "home_fibre_broadband",
                "url": url,
                "period_label": "2025",
            }
            with self.subTest(source_id=source_id):
                rows = _parse_page(source, {"status": 200, "text": text}, "2026-07-03T00:00:00+08:00", "2025")
                by_fee = {row["monthly_fee_hkd"]: row for row in rows}
                self.assertEqual(set(by_fee), {"198", "109", "119"})
                self.assertEqual(by_fee["198"]["contract_months"], "24")
                self.assertEqual(by_fee["109"]["contract_months"], "36")
                self.assertEqual(by_fee["119"]["source_status"], "public_third_party_offer_listing_needs_review")

    def test_parse_hgc_mytv_2025_mytvsuper_service_fee_row(self) -> None:
        source = {
            "source_id": "hgc_mytv_2025_mytvsuper_service_fee",
            "brand": "HGC",
            "product_category": "home_fibre_broadband",
            "url": "https://promo.mytvsuper.com/tc/service-fee/hgc",
            "period_label": "2025",
        }
        rows = _parse_page(source, {"status": 200, "text": HGC_MYTV_SERVICE_FEE_2025_TEXT}, "2026-07-03T00:00:00+08:00", "2025")
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["plan_name"], "HGC Fibre Broadband with myTV Gold service")
        self.assertEqual(row["monthly_fee_hkd"], "198")
        self.assertEqual(row["contract_months"], "24")
        self.assertEqual(row["source_status"], "public_partner_service_fee_needs_review")

    def test_parse_hgc_ezone_2019_public_comparison_rows(self) -> None:
        source = {
            "source_id": "hgc_ezone_2019_2g_broadband_comparison",
            "brand": "HGC",
            "product_category": "home_fibre_broadband",
            "url": "https://ezone.hk/article/2245977/%E6%A5%B5%E9%80%9F-2Gbps-%E5%AE%B6%E7%94%A8%E5%AF%AC%E9%A0%BB-%E4%B8%89%E5%A4%A7-ISP-%E6%9C%8D%E5%8B%99%E8%A8%88%E5%8A%83%E6%A0%BC%E5%83%B9",
            "period_label": "2019",
        }
        rows = _parse_page(source, {"status": 200, "text": HGC_EZONE_2019_TEXT}, "2026-07-03T00:00:00+08:00", "2019")
        self.assertEqual(len(rows), 3)
        by_name = {row["plan_name"]: row for row in rows}
        self.assertEqual(by_name["HGC 四線 2.2Gbps 光纖寬頻服務 average HK$218"]["average_monthly_fee_hkd"], "218")
        self.assertEqual(by_name["HGC 1Gbps 極速光纖寬頻服務 average HK$148"]["broadband_speed_mbps"], "1000")
        self.assertEqual(by_name["HGC Wi-Fi 360 add-on HK$58"]["monthly_fee_hkd"], "58")
        self.assertEqual(by_name["HGC Wi-Fi 360 add-on HK$58"]["broadband_speed_mbps"], "2200")
        self.assertTrue(all(row["source_status"] == "public_media_comparison_needs_review" for row in rows))
        self.assertTrue(all(row["plan_family"] == "HGC Home Broadband" for row in rows))

    def test_parse_hgc_line_for_four_2018_tc_official_page_rows(self) -> None:
        source = {
            "source_id": "hgc_line_for_four_2018_official_tc",
            "brand": "HGC",
            "product_category": "home_fibre_broadband",
            "url": "https://www.hgc.com.hk/zh/press-releases/hgc-broadband-launches-line-for-four-2-2g-fibre-broadband-and-wi-fi-360-services",
            "period_label": "2018",
        }
        rows = _parse_page(source, {"status": 200, "text": HGC_LINE_FOR_FOUR_2018_TC_TEXT}, "2026-07-07T00:00:00+08:00", "2018")
        self.assertEqual(len(rows), 2)
        by_fee = {row["monthly_fee_hkd"]: row for row in rows}
        self.assertEqual(by_fee["218"]["plan_name"], "HGC 一家四口 2.2G 光纖寬頻連 myTV SUPER HK$218 起")
        self.assertEqual(by_fee["218"]["tariff_type"], "monthly_bundle_fee")
        self.assertEqual(by_fee["58"]["tariff_type"], "monthly_value_added_service_fee")
        self.assertTrue(all(row["broadband_speed_mbps"] == "2200" for row in rows))
        self.assertTrue(all(row["source_status"] == "parsed_current_official_page_tc" for row in rows))
        self.assertTrue(all(row["plan_family"] == "HGC Home Broadband" for row in rows))

    def test_parse_hgc_2g_2023_public_launch_rows(self) -> None:
        for source_id, expected_status in [
            ("hgc_2g_2023_official_pdf", "parsed_public_official_pdf"),
            ("hgc_2g_2023_telecomreviewamericas", "public_press_syndication_needs_review"),
        ]:
            with self.subTest(source_id=source_id):
                source = {
                    "source_id": source_id,
                    "brand": "HGC",
                    "product_category": "home_fibre_broadband",
                    "url": "https://www.hgc.com.hk/assets/images/2023_12_11_EN.pdf",
                    "period_label": "2023",
                }
                rows = _parse_page(source, {"status": 200, "text": HGC_2G_2023_TEXT}, "2026-07-07T00:00:00+08:00", "2023")
                self.assertEqual(len(rows), 1)
                row = rows[0]
                self.assertEqual(row["plan_name"], "HGC 2G 2000Mbps broadband with Wi-Fi 6 Router HK$139")
                self.assertEqual(row["monthly_fee_hkd"], "139")
                self.assertEqual(row["broadband_speed_mbps"], "2000")
                self.assertEqual(row["tariff_type"], "monthly_plan_fee")
                self.assertEqual(row["source_status"], expected_status)
                self.assertIn("31 December 2023", row["add_on_charges_hkd"])

    def test_parse_hgc_on_air_plan_current_en_tc_pages(self) -> None:
        for source_id, text in [
            ("hgc_on_air_plan_en", HGC_ON_AIR_PLAN_EN_TEXT),
            ("hgc_on_air_plan_tc", HGC_ON_AIR_PLAN_TC_TEXT),
        ]:
            with self.subTest(source_id=source_id):
                source = {
                    "source_id": source_id,
                    "brand": "HGC",
                    "product_category": "wifi_pass",
                    "url": "https://hub.hgc.com.hk/HGConAir/Plan.do",
                }
                rows = _parse_page(source, {"status": 200, "text": text}, "2026-07-06T00:00:00+08:00", "current")
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["plan_name"], "HGC on air HK$58")
                self.assertEqual(rows[0]["monthly_fee_hkd"], "58")
                self.assertEqual(rows[0]["tariff_type"], "monthly_plan_fee")
                self.assertEqual(rows[0]["source_status"], "parsed_current")

    def test_parse_hgc_smart_home_living_2020_official_sources(self) -> None:
        sources = [
            {
                "source_id": "hgc_smart_home_living_2020_press",
                "brand": "HGC",
                "product_category": "home_fibre_broadband",
                "url": "https://www.hgc.com.hk/press-releases/hgc-broadband-launches-smart-home-living-offer-for-building-your-ideal-smart-home",
                "period_label": "2020",
            },
            {
                "source_id": "hgc_smart_home_living_2020_official_pdf",
                "brand": "HGC",
                "product_category": "home_fibre_broadband",
                "url": "https://www.hgc.com.hk/assets/images/2020_10_23_Eng.pdf",
                "period_label": "2020",
            },
        ]
        rows = []
        for source in sources:
            rows.extend(_parse_page(source, {"status": 200, "text": HGC_SMART_HOME_LIVING_2020_TEXT}, "2026-07-03T00:00:00+08:00", "2020"))
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(row["plan_name"] == "HGC 1G Home Broadband with smart home kit HK$119" for row in rows))
        self.assertTrue(all(row["monthly_fee_hkd"] == "119" for row in rows))
        self.assertTrue(all(row["broadband_speed_mbps"] == "1000" for row in rows))
        self.assertTrue(all(row["plan_family"] == "HGC Home Broadband" for row in rows))
        self.assertEqual({row["source_status"] for row in rows}, {"parsed_current", "parsed_public_official_pdf"})

    def test_parse_hgc_super_fun_2016_official_press_rows(self) -> None:
        source = {
            "source_id": "hgc_super_fun_2016_official_press",
            "brand": "HGC",
            "product_category": "home_fibre_broadband",
            "url": "https://www.hthkh.com/tc/ir/press.php?prid=/press/cp160314",
            "period_label": "2016",
        }
        rows = _parse_page(source, {"status": 200, "text": HGC_SUPER_FUN_2016_TEXT}, "2026-07-03T00:00:00+08:00", "2016")
        by_speed = {row["broadband_speed_mbps"]: row for row in rows}
        self.assertEqual(set(by_speed), {"100", "1000"})
        self.assertEqual(by_speed["100"]["monthly_fee_hkd"], "138")
        self.assertEqual(by_speed["1000"]["monthly_fee_hkd"], "188")
        self.assertTrue(all(row["source_status"] == "parsed_current" for row in rows))

    def test_parse_hgc_super_fun_2016_english_press_crosscheck(self) -> None:
        source = {
            "source_id": "hgc_super_fun_2016_official_press_en",
            "brand": "HGC",
            "product_category": "home_fibre_broadband",
            "url": "https://www.hthkh.com/en/ir/press.php?prid=/press/cp160314",
            "period_label": "2016",
        }
        rows = _parse_page(source, {"status": 200, "text": HGC_SUPER_FUN_2016_EN_TEXT}, "2026-07-03T00:00:00+08:00", "2016")
        by_speed = {row["broadband_speed_mbps"]: row for row in rows}
        self.assertEqual(set(by_speed), {"100", "1000"})
        self.assertEqual(by_speed["100"]["monthly_fee_hkd"], "138")
        self.assertEqual(by_speed["1000"]["monthly_fee_hkd"], "188")

    def test_parse_hgc_mobile_2026_press_and_syndication_rows(self) -> None:
        sources = [
            {
                "source_id": "hgc_mobile_launch_2026_press",
                "brand": "HGC",
                "product_category": "mobile_consumer_5g",
                "url": "https://www.hgc.com.hk/press-releases/hgc-announces-the-launch-of-hgc-mobile-expanding-mobile-connectivity-footprint-with-enhanced-network-on-the-go-experience",
                "period_label": "2026",
            },
            {
                "source_id": "hgc_mobile_launch_2026_etnet",
                "brand": "HGC",
                "product_category": "mobile_consumer_5g",
                "url": "https://www.etnet.com.hk/www/tc/news/news-article.php?category=mediaoutreach&newsid=459236&section=index",
                "period_label": "2026",
            },
        ]
        rows = []
        for source in sources:
            rows.extend(_parse_page(source, {"status": 200, "text": HGC_MOBILE_LAUNCH_2026_TEXT}, "2026-07-03T00:00:00+08:00", "2026"))
        by_source_fee = {(row["source_id"], row["monthly_fee_hkd"]): row for row in rows}
        self.assertEqual(len(rows), 4)
        self.assertEqual(by_source_fee[("hgc_mobile_launch_2026_press", "98")]["local_data_gb"], "4")
        self.assertEqual(by_source_fee[("hgc_mobile_launch_2026_press", "285")]["broadband_speed_mbps"], "1000")
        self.assertEqual(by_source_fee[("hgc_mobile_launch_2026_press", "98")]["source_status"], "parsed_current")
        self.assertEqual(by_source_fee[("hgc_mobile_launch_2026_etnet", "285")]["source_status"], "public_press_release_syndication_needs_review")

    def test_parse_smartone_home_5g_2020_ezone_review_row(self) -> None:
        source = {
            "source_id": "smartone_home_5g_2020_ezone_review",
            "brand": "SmarTone",
            "product_category": "home_5g_broadband",
            "url": "https://ezone.hk/article/2753352/SmarTone-5G-%E5%AE%B6%E5%B1%85%E5%AF%AC%E9%A0%BB-148-%E6%9C%89%E5%BE%97%E7%8E%A9-%E5%B8%82%E5%8D%80-%E6%9D%91%E5%B1%8B%E5%AF%A6%E6%B8%AC",
            "period_label": "2020",
        }
        rows = _parse_page(source, {"status": 200, "text": SMARTONE_HOME_5G_EZONE_2020_TEXT}, "2026-07-03T00:00:00+08:00", "2020")
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["monthly_fee_hkd"], "148")
        self.assertEqual(row["local_data_gb"], "unlimited")
        self.assertEqual(row["source_status"], "public_media_review_needs_review")
        self.assertNotEqual(row["monthly_fee_hkd"], "2160")

    def test_parse_smartone_home_5g_2021_keeps_monthly_fee_despite_installation_text(self) -> None:
        source = {
            "source_id": "smartone_home_5g_2021_pdf",
            "brand": "SmarTone",
            "product_category": "home_5g_broadband",
            "url": "https://www.smartoneholdings.com/about/media_centre/press_release/press/2021/09/2021_09_14_448.pdf",
            "period_label": "2021",
        }
        rows = _parse_page(source, {"status": 200, "text": SMARTONE_HOME_5G_2021_TEXT}, "2026-07-03T00:00:00+08:00", "2021")
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["plan_name"], "SmarTone Home 5G Broadband HK$148 unlimited 5G data")
        self.assertEqual(row["monthly_fee_hkd"], "148")
        self.assertEqual(row["tariff_type"], "monthly_plan_fee")
        self.assertEqual(row["local_data_gb"], "")

    def test_parse_smartone_home_5g_2021_chinese_pdf_crosscheck(self) -> None:
        source = {
            "source_id": "smartone_home_5g_2021_pdf_chi",
            "brand": "SmarTone",
            "product_category": "home_5g_broadband",
            "url": "https://www.smartoneholdings.com/about/media_centre/press_release/press/2021/09/2021_09_14_448_chi.pdf",
            "period_label": "2021",
        }
        rows = _parse_page(source, {"status": 200, "text": SMARTONE_HOME_5G_2021_CHI_TEXT}, "2026-07-03T00:00:00+08:00", "2021")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["monthly_fee_hkd"], "148")
        self.assertEqual(rows[0]["tariff_type"], "monthly_plan_fee")

    def test_parse_smartone_home_5g_disney_offer_current(self) -> None:
        source = {
            "source_id": "smartone_home_5g_disney_offer_current",
            "brand": "SmarTone",
            "product_category": "home_5g_broadband",
            "url": "https://www.smartone.com/en/mobile_and_price_plans/offer_detail/disney-plus-special-offer/4883/",
        }
        rows = _parse_page(source, {"status": 200, "text": SMARTONE_HOME_5G_DISNEY_OFFER_CURRENT_TEXT}, "2026-07-06T00:00:00+08:00", "current")
        by_name = {row["plan_name"]: row for row in rows}
        self.assertEqual(len(rows), 4)
        self.assertEqual(by_name["SmarTone Home 5G Broadband WiFi 7 Plan HK$217"]["monthly_fee_hkd"], "217")
        self.assertEqual(by_name["SmarTone Home 5G Broadband WiFi 7 Mesh Plan HK$229"]["contract_months"], "36")
        self.assertEqual(by_name["SmarTone Home 5G Broadband WiFi 6 Plan HK$168 36-month"]["average_monthly_fee_hkd"], "168")
        self.assertEqual(by_name["SmarTone Home 5G Broadband WiFi 6 Plan HK$168 24-month"]["contract_months"], "24")
        self.assertTrue(all(row["source_status"] == "parsed_current_official_offer_page" for row in rows))

    def test_parse_smartone_home_5g_disney_offer_current_tc(self) -> None:
        source = {
            "source_id": "smartone_home_5g_disney_offer_current_tc",
            "brand": "SmarTone",
            "product_category": "home_5g_broadband",
            "url": "https://www.smartone.com/tc/mobile_and_price_plans/offer_detail/disney-plus-special-offer/4883/",
        }
        rows = _parse_page(source, {"status": 200, "text": SMARTONE_HOME_5G_DISNEY_OFFER_CURRENT_TC_TEXT}, "2026-07-06T00:00:00+08:00", "current")
        by_name = {row["plan_name"]: row for row in rows}
        self.assertEqual(len(rows), 4)
        self.assertEqual(by_name["SmarTone Home 5G Broadband WiFi 7 Plan HK$217"]["monthly_fee_hkd"], "217")
        self.assertEqual(by_name["SmarTone Home 5G Broadband WiFi 7 Mesh Plan HK$229"]["monthly_fee_hkd"], "229")
        self.assertEqual(by_name["SmarTone Home 5G Broadband WiFi 6 Plan HK$168 36-month"]["contract_months"], "36")
        self.assertIn("258/259", by_name["SmarTone Home 5G Broadband WiFi 6 Plan HK$168 36-month"]["add_on_charges_hkd"])
        self.assertEqual(by_name["SmarTone Home 5G Broadband WiFi 6 Plan HK$168 24-month"]["contract_months"], "24")

    def test_parse_smartone_learning_support_2022_chinese_pdf_crosscheck(self) -> None:
        source = {
            "source_id": "smartone_learning_support_2022_pdf_chi",
            "brand": "SmarTone",
            "product_category": "home_5g_broadband",
            "url": "https://www.smartoneholdings.com/about/media_centre/press_release/press/2022/04/2022_04_28_460_chi.pdf",
            "period_label": "2022",
        }
        rows = _parse_page(source, {"status": 200, "text": SMARTONE_LEARNING_SUPPORT_2022_CHI_TEXT}, "2026-07-03T00:00:00+08:00", "2022")
        by_fee = {row["monthly_fee_hkd"]: row for row in rows}
        self.assertEqual(set(by_fee), {"1600", "780"})
        self.assertEqual(by_fee["1600"]["tariff_type"], "annual_home_5g_broadband_support_fee")
        self.assertEqual(by_fee["780"]["tariff_type"], "router_rental_fee_waiver_value")
        self.assertEqual(by_fee["1600"]["broadband_speed_mbps"], "5000")
        self.assertTrue(all(row["source_status"] == "parsed_public_official_pdf" for row in rows))

    def test_parse_smartone_5g_launch_2020_pdf_skips_discount_noise(self) -> None:
        source = {
            "source_id": "smartone_5g_launch_2020_pdf",
            "brand": "SmarTone",
            "product_category": "mobile_consumer_5g",
            "url": "https://www.smartone.com/about_us/media_centre/press_release/2020/04/2020_04_07_01.pdf",
            "period_label": "2020",
        }
        rows = _parse_page(source, {"status": 200, "text": SMARTONE_5G_LAUNCH_2020_TEXT}, "2026-07-03T00:00:00+08:00", "2020")
        by_name = {row["plan_name"]: row for row in rows}
        fees = {row["monthly_fee_hkd"] for row in rows}
        self.assertEqual(by_name["SmarTone 5G Monthly Plan HK$398 80GB"]["local_data_gb"], "80")
        self.assertEqual(by_name["SmarTone 5G Monthly Plan HK$398 100GB promotional entitlement"]["local_data_gb"], "100")
        self.assertEqual(by_name["SmarTone 5G limited-time monthly offer HK$298 100GB"]["monthly_fee_hkd"], "298")
        self.assertEqual(by_name["SmarTone 5G unlimited local data top-up HK$80"]["tariff_type"], "monthly_data_addon_fee")
        self.assertTrue(all(row["source_status"] == "parsed_public_official_pdf" for row in rows))
        self.assertFalse(fees & {"2100", "10998", "8898", "18", "38", "48", "69"})

    def test_parse_smartone_5g_launch_2020_chinese_pdf_crosscheck(self) -> None:
        source = {
            "source_id": "smartone_5g_launch_2020_pdf_chi",
            "brand": "SmarTone",
            "product_category": "mobile_consumer_5g",
            "url": "https://www.smartoneholdings.com/about/media_centre/press_release/press/2020/05/2020_05_26_431_chi.pdf",
            "period_label": "2020",
        }
        rows = _parse_page(source, {"status": 200, "text": SMARTONE_5G_LAUNCH_2020_CHI_TEXT}, "2026-07-03T00:00:00+08:00", "2020")
        by_name = {row["plan_name"]: row for row in rows}
        self.assertEqual(len(rows), 6)
        self.assertEqual(by_name["SmarTone 5G Monthly Plan HK$398 80GB"]["local_data_gb"], "80")
        self.assertEqual(by_name["SmarTone 5G Monthly Plan HK$398 100GB promotional entitlement"]["local_data_gb"], "100")
        self.assertEqual(by_name["SmarTone 5G limited-time monthly offer HK$298 100GB"]["monthly_fee_hkd"], "298")
        self.assertEqual(by_name["SmarTone 5G unlimited local data top-up HK$80"]["post_fup_speed_mbps"], "5")
        self.assertEqual(by_name["SmarTone 5G local data top-up HK$50 10GB"]["local_data_gb"], "10")
        self.assertEqual(by_name["SmarTone 5G add-on SIM HK$120 50GB"]["local_data_gb"], "50")

    def test_parse_smartone_gamergizer_2020_pdf_skips_discount_noise(self) -> None:
        source = {
            "source_id": "smartone_gamergizer_2020_pdf",
            "brand": "SmarTone",
            "product_category": "mobile_consumer_5g",
            "url": "https://www.smartone.com/about_us/media_centre/press_release/2020/08/2020_08_25_01.pdf",
            "period_label": "2020",
        }
        rows = _parse_page(source, {"status": 200, "text": SMARTONE_GAMERGIZER_2020_TEXT}, "2026-07-03T00:00:00+08:00", "2020")
        by_name = {row["plan_name"]: row for row in rows}
        fees = {row["monthly_fee_hkd"] for row in rows}
        self.assertEqual(by_name["SmarTone Gamergizer average monthly service fee HK$29"]["tariff_type"], "monthly_value_added_service_fee")
        self.assertEqual(by_name["SmarTone 5G Monthly Plan HK$398 100GB"]["local_data_gb"], "100")
        self.assertEqual(by_name["SmarTone 5G Gamergizer limited-time monthly offer HK$298"]["monthly_fee_hkd"], "298")
        self.assertEqual(by_name["SmarTone 5G add-on SIM HK$120 50GB"]["tariff_type"], "monthly_addon_sim_fee")
        self.assertFalse(fees & {"2100", "1200", "640", "160", "18"})

    def test_parse_smartone_gamergizer_2020_chinese_pdf_crosscheck(self) -> None:
        source = {
            "source_id": "smartone_gamergizer_2020_pdf_chi",
            "brand": "SmarTone",
            "product_category": "mobile_consumer_5g",
            "url": "https://www.smartoneholdings.com/about/media_centre/press_release/press/2020/07/2020_07_14_432_chi.pdf",
            "period_label": "2020",
        }
        rows = _parse_page(source, {"status": 200, "text": SMARTONE_GAMERGIZER_2020_CHI_TEXT}, "2026-07-03T00:00:00+08:00", "2020")
        by_name = {row["plan_name"]: row for row in rows}
        self.assertEqual(len(rows), 6)
        self.assertEqual(by_name["SmarTone Gamergizer average monthly service fee HK$29"]["average_monthly_fee_hkd"], "29")
        self.assertEqual(by_name["SmarTone 5G Monthly Plan HK$398 100GB"]["local_data_gb"], "100")
        self.assertEqual(by_name["SmarTone 5G Gamergizer limited-time monthly offer HK$298"]["monthly_fee_hkd"], "298")
        self.assertEqual(by_name["SmarTone 5G unlimited local data top-up HK$80"]["local_data_gb"], "unlimited")
        self.assertEqual(by_name["SmarTone 5G local data top-up HK$50 10GB"]["local_data_gb"], "10")
        self.assertEqual(by_name["SmarTone 5G add-on SIM HK$120 50GB"]["local_data_gb"], "50")

    def test_parse_smartone_1c2n_2024_chinese_pdf_crosscheck(self) -> None:
        source = {
            "source_id": "smartone_1c2n_2024_pdf_chi",
            "brand": "SmarTone",
            "product_category": "mobile_value_added_service",
            "url": "https://www.smartoneholdings.com/about/media_centre/press_release/press/2024/04/2024_04_19_504_chi.pdf",
            "period_label": "2024",
        }
        rows = _parse_page(source, {"status": 200, "text": SMARTONE_1C2N_2024_CHI_TEXT}, "2026-07-03T00:00:00+08:00", "2024")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["monthly_fee_hkd"], "28")
        self.assertEqual(rows[0]["tariff_type"], "monthly_value_added_service_fee")

    def test_parse_smartone_home_5g_wifi7_2025_chinese_pdf_crosscheck(self) -> None:
        source = {
            "source_id": "smartone_home_5g_wifi7_2025_pdf_chi",
            "brand": "SmarTone",
            "product_category": "home_5g_broadband",
            "url": "https://www.smartoneholdings.com/about/media_centre/press_release/press/2025/01/2025_01_15_514_chi.pdf",
            "period_label": "2025",
        }
        rows = _parse_page(source, {"status": 200, "text": SMARTONE_HOME_5G_WIFI7_2025_CHI_TEXT}, "2026-07-03T00:00:00+08:00", "2025")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["monthly_fee_hkd"], "191")
        self.assertEqual(rows[0]["average_monthly_fee_hkd"], "191")

    def test_parse_smartone_st_protect_chinese_pdf_crosscheck(self) -> None:
        source = {
            "source_id": "smartone_st_protect_2016_pdf_chi",
            "brand": "SmarTone",
            "product_category": "mobile_value_added_service",
            "url": "https://www.smartoneholdings.com/about/media_centre/press_release/press/2016/06/ST_Protect_press_release_chi.pdf",
            "period_label": "2016",
        }
        rows = _parse_page(source, {"status": 200, "text": SMARTONE_ST_PROTECT_CHI_TEXT}, "2026-07-03T00:00:00+08:00", "2016")
        by_name = {row["plan_name"]: row for row in rows}
        self.assertEqual(by_name["SmarTone ST Protect standard plan HK$28"]["monthly_fee_hkd"], "28")
        self.assertEqual(by_name["SmarTone ST Protect monthly plan contract offer HK$18"]["contract_months"], "12")
        self.assertTrue(all(row["source_status"] == "parsed_public_official_pdf" for row in rows))

    def test_parse_smartone_roaming_multiday_linkedin_crosscheck(self) -> None:
        source = {
            "source_id": "smartone_roaming_multiday_2023_linkedin",
            "brand": "SmarTone",
            "product_category": "roaming_data_pack",
            "url": "https://www.linkedin.com/posts/smartone_smartone-5g-roaming-activity-7047852825325817856-TVKF",
            "period_label": "2023",
        }
        rows = _parse_page(source, {"status": 200, "text": SMARTONE_ROAMING_MULTIDAY_LINKEDIN_TEXT}, "2026-07-03T00:00:00+08:00", "2023")
        by_name = {row["plan_name"]: row for row in rows}
        self.assertEqual(by_name["SmarTone 4-Day Multi-Day Roaming Data Pack HK$128"]["average_monthly_fee_hkd"], "28.8")
        self.assertEqual(by_name["SmarTone 7-Day Multi-Day Roaming Data Pack HK$198"]["average_monthly_fee_hkd"], "25.5")
        self.assertTrue(all(row["source_status"] == "public_official_social_post_needs_review" for row in rows))

    def test_parse_smartone_roaming_pack_current_fees_only(self) -> None:
        source = {
            "source_id": "smartone_roaming_pack",
            "brand": "SmarTone",
            "product_category": "roaming_data_pack",
            "url": "https://5g.smartone.com/en/mobile_and_price_plans/roaming/apac_worldwide_roaming_data_pack/charges.jsp",
        }
        rows = _parse_page(source, {"status": 200, "text": SMARTONE_ROAMING_PACK_TEXT}, "2026-07-06T00:00:00+08:00", "current")
        by_name = {row["plan_name"]: row for row in rows}
        fees = {row["monthly_fee_hkd"] for row in rows}
        self.assertEqual(len(rows), 4)
        self.assertEqual(by_name["SmarTone APAC Roaming Data Pack HK$269 10GB"]["roaming_data_gb"], "10")
        self.assertEqual(by_name["SmarTone APAC Roaming Data Pack top-up HK$38 1GB"]["tariff_type"], "roaming_data_top_up_fee")
        self.assertEqual(by_name["SmarTone Worldwide Roaming Data Pack HK$549 10GB"]["roaming_data_gb"], "10")
        self.assertEqual(by_name["SmarTone Worldwide Roaming Data Pack top-up HK$68 1GB"]["tariff_type"], "roaming_data_top_up_fee")
        self.assertFalse(fees & {"3", "6", "99", "178"})

    def test_parse_smartone_roaming_pack_tc_current_fees_only(self) -> None:
        source = {
            "source_id": "smartone_roaming_pack_tc",
            "brand": "SmarTone",
            "product_category": "roaming_data_pack",
            "url": "https://5g.smartone.com/tc/mobile_and_price_plans/roaming/apac_worldwide_roaming_data_pack/charges.jsp",
        }
        rows = _parse_page(source, {"status": 200, "text": SMARTONE_ROAMING_PACK_TC_TEXT}, "2026-07-06T00:00:00+08:00", "current")
        by_name = {row["plan_name"]: row for row in rows}
        fees = {row["monthly_fee_hkd"] for row in rows}
        self.assertEqual(len(rows), 4)
        self.assertEqual(by_name["SmarTone APAC Roaming Data Pack HK$269 10GB"]["roaming_data_gb"], "10")
        self.assertEqual(by_name["SmarTone APAC Roaming Data Pack top-up HK$38 1GB"]["tariff_type"], "roaming_data_top_up_fee")
        self.assertEqual(by_name["SmarTone Worldwide Roaming Data Pack HK$549 10GB"]["roaming_data_gb"], "10")
        self.assertEqual(by_name["SmarTone Worldwide Roaming Data Pack top-up HK$68 1GB"]["tariff_type"], "roaming_data_top_up_fee")
        self.assertFalse(fees & {"3", "6", "99", "178"})

    def test_parse_smartone_roaming_yas_2023_chinese_pdf_crosscheck(self) -> None:
        source = {
            "source_id": "smartone_roaming_yas_2023_pdf_chi",
            "brand": "SmarTone",
            "product_category": "roaming_data_pack",
            "url": "https://www.smartoneholdings.com/about/media_centre/press_release/press/2023/03/2023_03_02_487_chi.pdf",
            "period_label": "2023",
        }
        rows = _parse_page(source, {"status": 200, "text": SMARTONE_ROAMING_YAS_2023_CHI_TEXT}, "2026-07-03T00:00:00+08:00", "2023")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["monthly_fee_hkd"], "23")
        self.assertEqual(rows[0]["tariff_type"], "daily_pass_fee")

    def test_parse_hkbn_homeplus_5g_2021_pdf_skips_rewards_noise(self) -> None:
        source = {
            "source_id": "hkbn_homeplus_5g_2021_pdf",
            "brand": "HKBN",
            "product_category": "mobile_consumer_5g",
            "url": "https://www.hkbn.net/pdf/en/HKBN_HOMEPLUS_5G_2021.pdf",
            "period_label": "2021",
        }
        rows = _parse_page(source, {"status": 200, "text": HKBN_HOMEPLUS_5G_2021_TEXT}, "2026-07-03T00:00:00+08:00", "2021")
        by_name = {row["plan_name"]: row for row in rows}
        fees = {row["monthly_fee_hkd"] for row in rows}
        self.assertEqual(by_name["HKBN 5G Unlimited Data Plan HK$298 20GB"]["local_data_gb"], "20")
        self.assertEqual(by_name["HKBN 5G Unlimited Data Plan HK$338 30GB"]["local_data_gb"], "30")
        self.assertEqual(by_name["HKBN 5G Basic Plan HK$238 20GB"]["local_data_gb"], "20")
        self.assertEqual(by_name["HKBN 5G Basic Plan HK$278 30GB"]["local_data_gb"], "30")
        self.assertEqual(by_name["HKBN 5G local data top-up HK$388 100GB"]["tariff_type"], "monthly_data_addon_fee")
        self.assertEqual(by_name["HKBN 5G local data top-up HK$30 5GB"]["tariff_type"], "monthly_data_addon_fee")
        self.assertFalse(fees & {"10", "18", "600", "800", "2000", "2400", "2800"})

    def test_parse_hkbn_homeplus_techent_2021_crosscheck(self) -> None:
        source = {
            "source_id": "hkbn_homeplus_5g_2021_techent_syndication",
            "brand": "HKBN",
            "product_category": "mobile_consumer_5g",
            "url": "https://techent.tv/2021/04/23/hkbn-homeplus/",
            "period_label": "2021",
        }
        rows = _parse_page(source, {"status": 200, "text": HKBN_HOMEPLUS_TECHENT_2021_TEXT}, "2026-07-03T00:00:00+08:00", "2021")
        self.assertEqual(
            {(row["monthly_fee_hkd"], row["local_data_gb"]) for row in rows},
            {("298", "20"), ("338", "30"), ("238", "20"), ("278", "30"), ("388", "100"), ("30", "5")},
        )
        self.assertTrue(all(row["source_status"] == "public_press_release_syndication_needs_review" for row in rows))

    def test_parse_hkbn_crossborder_5g_2023_official_rows(self) -> None:
        source = {
            "source_id": "hkbn_crossborder_5g_2023_official",
            "brand": "HKBN",
            "product_category": "mobile_consumer_5g",
            "url": "https://www.hkbn.net/group/en/newsroom/press-releases/20230525_FY23_HKBN_Launches_Cross-border_5G_Local_1GB_GBA_Data_Plans_Disruptive_Mobile_Service_Plans",
            "period_label": "2023",
        }
        rows = _parse_page(source, {"status": 200, "text": HKBN_CROSSBORDER_5G_2023_TEXT}, "2026-07-03T00:00:00+08:00", "2023")
        by_name = {row["plan_name"]: row for row in rows}
        self.assertEqual(len(rows), 2)
        self.assertEqual(by_name["HKBN 5G Home Broadband HK$103 10GB"]["roaming_data_gb"], "1")
        self.assertEqual(by_name["HKBN 5G Home Broadband HK$149 30GB"]["monthly_fee_hkd"], "149")
        self.assertEqual(by_name["HKBN 5G Home Broadband HK$149 30GB"]["local_data_gb"], "30")
        self.assertNotIn("HKBN 5G Home Broadband HK$38 2GB", by_name)
        self.assertTrue(all(row["tariff_type"] == "monthly_crossborder_5g_plan_fee" for row in rows))

    def test_parse_hkbn_5g_home_broadband_terms_pdf(self) -> None:
        source = {
            "source_id": "hkbn_5g_home_broadband_terms_pdf",
            "brand": "HKBN",
            "product_category": "home_5g_broadband",
            "url": "https://www.hkbn.net/personal/cmsdata/content/queryPdfContents/6FRs5S4DySv8i5UozrSTeZQtiZm951BEMaSuWenOo.pdf",
        }
        rows = _parse_page(source, {"status": 200, "text": HKBN_5G_HOME_BROADBAND_TERMS_TEXT}, "2026-07-06T00:00:00+08:00", "current")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["monthly_fee_hkd"], "118")
        self.assertEqual(rows[0]["local_data_gb"], "300")
        self.assertEqual(rows[0]["contract_months"], "24")
        self.assertIn("monthly administration fee", rows[0]["add_on_charges_hkd"])
        self.assertEqual(rows[0]["source_status"], "parsed_public_official_pdf")

    def test_parse_hkbn_5g_home_broadband_terms_pdf_202405(self) -> None:
        source = {
            "source_id": "hkbn_5g_home_broadband_terms_pdf_202405",
            "brand": "HKBN",
            "product_category": "home_5g_broadband",
            "url": "https://images.hkbn.net/apply/orpres/broadband/tc_pdf/MS_5G%20BN_3HK_%24118%20SIM%20Only%20PlanT%26C_%20ENG_202405.pdf",
        }
        rows = _parse_page(source, {"status": 200, "text": HKBN_5G_HOME_BROADBAND_TERMS_202405_TEXT}, "2026-07-06T00:00:00+08:00", "current")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["plan_name"], "HKBN 5G Home Broadband Service Plan HK$118")
        self.assertEqual(rows[0]["monthly_fee_hkd"], "118")
        self.assertEqual(rows[0]["local_data_gb"], "300")
        self.assertEqual(rows[0]["contract_months"], "24")
        self.assertEqual(rows[0]["source_status"], "parsed_public_official_pdf")

    def test_parse_hkbn_5g_home_broadband_current_page(self) -> None:
        source = {
            "source_id": "hkbn_5g_home_broadband",
            "brand": "HKBN",
            "product_category": "home_5g_broadband",
            "url": "https://www.hkbn.net/personal/5g-home-broadband/en",
        }
        rows = _parse_page(source, {"status": 200, "text": HKBN_5G_HOME_BROADBAND_CURRENT_TEXT}, "2026-07-07T00:00:00+08:00", "current")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["plan_name"], "HKBN 5G Home Broadband Service Plan HK$118")
        self.assertEqual(rows[0]["monthly_fee_hkd"], "118")
        self.assertEqual(rows[0]["local_data_gb"], "300")
        self.assertEqual(rows[0]["contract_months"], "24")
        self.assertEqual(rows[0]["source_status"], "parsed_current_official_page")

    def test_parse_hgc_25g_2023_home_telephone_addon_not_broadband_fee(self) -> None:
        source = {
            "source_id": "hgc_25g_2023_official",
            "brand": "HGC",
            "product_category": "home_fibre_broadband",
            "url": "https://www.hgc.com.hk/press-releases/hgc-broadband-launches-2-5g-broadband-service",
            "period_label": "2023",
        }
        rows = _parse_page(source, {"status": 200, "text": HGC_25G_2023_TEXT}, "2026-07-03T00:00:00+08:00", "2023")
        by_name = {row["plan_name"]: row for row in rows}
        self.assertEqual(by_name["HGC 2.5G broadband with TP-Link Deco XE75 Pro Wi-Fi 6 router HK$298"]["broadband_speed_mbps"], "2500")
        self.assertEqual(by_name["HGC Home Telephone add-on for 2.5G broadband HK$30"]["broadband_speed_mbps"], "")
        self.assertEqual(by_name["HGC Home Telephone add-on for 2.5G broadband HK$30"]["tariff_type"], "monthly_value_added_service_fee")

    def test_parse_hgc_terms_2026_tc_standard_monthly_fee_rows(self) -> None:
        source = {
            "source_id": "hgc_home_broadband_terms_standard_monthly_2026_tc",
            "brand": "HGC",
            "product_category": "home_fibre_broadband",
            "url": "https://www.hgcbroadband.com/tc/pages/terms-conditions",
            "period_label": "2026",
        }
        rows = _parse_page(source, {"status": 200, "text": HGC_TERMS_TC_2026_TEXT}, "2026-07-03T00:00:00+08:00", "2026")
        by_speed = {row["broadband_speed_mbps"]: row for row in rows}

        self.assertEqual(len(rows), 12)
        self.assertEqual(by_speed["500"]["monthly_fee_hkd"], "448")
        self.assertEqual(by_speed["1000"]["monthly_fee_hkd"], "598")
        self.assertEqual(by_speed["500"]["tariff_type"], "terms_after_minimum_period_monthly_fee_reference")
        self.assertEqual(by_speed["500"]["source_status"], "parsed_current_terms_reference")

    def test_hgc_official_standard_monthly_tc_crosscheck_avoids_terms_conflict(self) -> None:
        product_source = {
            "source_id": "hgc_home_broadband_standard_monthly_2026",
            "brand": "HGC",
            "product_category": "home_fibre_broadband",
            "url": "https://www.hgcbroadband.com/en/broadband/fibre-to-home",
            "period_label": "2026",
        }
        product_tc_source = {
            "source_id": "hgc_home_broadband_standard_monthly_2026_tc",
            "brand": "HGC",
            "product_category": "home_fibre_broadband",
            "url": "https://www.hgcbroadband.com/tc/broadband/fibre-to-home",
            "period_label": "2026",
        }
        terms_en_source = {
            "source_id": "hgc_home_broadband_terms_standard_monthly_2026",
            "brand": "HGC",
            "product_category": "home_fibre_broadband",
            "url": "https://www.hgcbroadband.com/en/pages/terms-conditions",
            "period_label": "2026",
        }
        terms_tc_source = {
            "source_id": "hgc_home_broadband_terms_standard_monthly_2026_tc",
            "brand": "HGC",
            "product_category": "home_fibre_broadband",
            "url": "https://www.hgcbroadband.com/tc/pages/terms-conditions",
            "period_label": "2026",
        }
        rows = [
            *_parse_page(product_source, {"status": 200, "text": HGC_CURRENT_FIBRE_TEXT}, "2026-07-03T00:00:00+08:00", "2026"),
            *_parse_page(product_tc_source, {"status": 200, "text": HGC_CURRENT_FIBRE_TC_TEXT}, "2026-07-03T00:00:00+08:00", "2026"),
            *_parse_page(terms_en_source, {"status": 200, "text": HGC_TERMS_TC_2026_TEXT}, "2026-07-03T00:00:00+08:00", "2026"),
            *_parse_page(terms_tc_source, {"status": 200, "text": HGC_TERMS_TC_2026_TEXT}, "2026-07-03T00:00:00+08:00", "2026"),
        ]

        _apply_verification(rows)

        five_hundred_rows = [row for row in rows if row["broadband_speed_mbps"] == "500"]
        one_gig_rows = [row for row in rows if row["broadband_speed_mbps"] == "1000"]
        self.assertEqual({row["monthly_fee_hkd"] for row in five_hundred_rows}, {"448", "488"})
        official_500_rows = [row for row in five_hundred_rows if row["source_id"].startswith("hgc_home_broadband_standard_monthly_2026")]
        terms_500_rows = [row for row in five_hundred_rows if row["source_status"] == "parsed_current_terms_reference"]
        self.assertTrue(all(row["verification_status"] == "multi_source_or_multi_snapshot_verified" for row in official_500_rows))
        self.assertTrue(all(row["tariff_type"] == "terms_after_minimum_period_monthly_fee_reference" for row in terms_500_rows))
        self.assertTrue(all(row["verification_status"] != "official_price_conflict_needs_review" for row in five_hundred_rows))
        self.assertTrue(all(row["verification_status"] == "multi_source_or_multi_snapshot_verified" for row in one_gig_rows))

    def test_parse_smartone_aquos_pcm_2017_crosscheck(self) -> None:
        source = {
            "source_id": "smartone_aquos_s2_2017_pcm_report",
            "brand": "SmarTone",
            "product_category": "mobile_consumer_4g",
            "url": "https://www.pcmarket.com.hk/aquos-s2/",
            "period_label": "2017",
        }
        rows = _parse_page(source, {"status": 200, "text": SMARTONE_AQUOS_PCM_2017_TEXT}, "2026-07-03T00:00:00+08:00", "2017")
        self.assertEqual(
            {(row["monthly_fee_hkd"], row["local_data_gb"]) for row in rows},
            {("388", "6"), ("348", "2.5"), ("258", "1")},
        )
        self.assertTrue(all(row["contract_months"] == "24" for row in rows))
        self.assertTrue(all(row["source_status"] == "public_media_report_needs_review" for row in rows))

    def test_parse_smartone_aquos_2017_chinese_official_pdf_crosscheck(self) -> None:
        source = {
            "source_id": "smartone_aquos_s2_supercare_2017_pdf_chi",
            "brand": "SmarTone",
            "product_category": "mobile_consumer_4g",
            "url": "https://www.smartoneholdings.com/about/media_centre/press_release/press/2017/11/2017_11_23_401_chi.pdf",
            "period_label": "2017",
        }
        rows = _parse_page(source, {"status": 200, "text": SMARTONE_AQUOS_S2_2017_CHI_TEXT}, "2026-07-03T00:00:00+08:00", "2017")
        by_fee_data = {(row["monthly_fee_hkd"], row["local_data_gb"]): row for row in rows}
        self.assertEqual(
            set(by_fee_data),
            {("388", "6"), ("348", "2.5"), ("258", "1"), ("308", "2.5"), ("218", "1")},
        )
        self.assertEqual(by_fee_data[("308", "2.5")]["local_voice"], "3000 minutes")
        self.assertEqual(by_fee_data[("218", "1")]["add_on_charges_hkd"], "580")
        self.assertTrue(all(row["source_status"] == "parsed_public_official_pdf" for row in rows))

    def test_parse_icable_broadbandqueen_2024_public_offer_rows(self) -> None:
        for source_id, url in [
            (
                "icable_broadbandqueen_2024_public_offer",
                "https://www.broadbandqueen.com/en/post/i-cable-%E5%AF%9B%E9%A0%BB%E5%84%AA%E6%83%A0/",
            ),
            (
                "icable_broadbandqueen_2024_public_offer_tc",
                "https://www.broadbandqueen.com/post/i-cable-%E5%AF%9B%E9%A0%BB%E5%84%AA%E6%83%A0/",
            ),
        ]:
            source = {
                "source_id": source_id,
                "brand": "i-CABLE",
                "product_category": "home_fibre_broadband",
                "url": url,
                "period_label": "2024",
            }
            rows = _parse_page(source, {"status": 200, "text": ICABLE_BROADBANDQUEEN_2024_TEXT}, "2026-07-03T00:00:00+08:00", "2024")
            by_speed = {row["broadband_speed_mbps"]: row for row in rows}
            self.assertEqual(set(by_speed), {"100", "500", "1000"})
            self.assertEqual(by_speed["100"]["monthly_fee_hkd"], "78")
            self.assertEqual(by_speed["500"]["monthly_fee_hkd"], "128")
            self.assertEqual(by_speed["1000"]["monthly_fee_hkd"], "168")
            self.assertTrue(all(row["source_status"] == "public_third_party_offer_listing_needs_review" for row in rows))

    def test_parse_icable_findplanking_2022_only_keeps_corroborated_rows(self) -> None:
        source = {
            "source_id": "icable_findplanking_2022_offer_listing",
            "brand": "i-CABLE",
            "product_category": "home_fibre_broadband",
            "url": "https://findplanking.com/broadband/-LdLAzZv7h2jBUoAg6Fr",
            "period_label": "2022",
        }
        rows = _parse_page(source, {"status": 200, "text": ICABLE_FINDPLANKING_2022_TEXT}, "2026-07-06T00:00:00+08:00", "2022")
        speed_fee = {(row["broadband_speed_mbps"], row["monthly_fee_hkd"]) for row in rows}

        self.assertEqual(speed_fee, {("200", "58"), ("1000", "88")})
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(row["source_status"] == "public_third_party_offer_listing_needs_review" for row in rows))

    def test_parse_hk01_2026_broadband_comparison_rows(self) -> None:
        cases = [
            ("hkbn_hk01_broadband_comparison_2026", "HKBN", "88", "24", "public_housing_reference"),
            ("hgc_hk01_broadband_comparison_2026", "HGC", "109", "24/36", "market_reference"),
            ("hgc_hk01_public_housing_109_broadband_comparison_2026", "HGC", "109", "24", "public_housing_reference"),
            ("smartone_hk01_broadband_comparison_2026", "SmarTone", "88", "36", "market_reference"),
            ("icable_hk01_broadband_comparison_2026", "i-CABLE", "88", "36", "market_reference"),
        ]
        for source_id, brand, fee, contract_months, segment in cases:
            source = {
                "source_id": source_id,
                "brand": brand,
                "product_category": "home_fibre_broadband",
                "url": "https://www.hk01.com/example",
                "period_label": "2026",
            }
            rows = _parse_page(source, {"status": 200, "text": HK01_BROADBAND_2026_TEXT}, "2026-07-03T00:00:00+08:00", "2026")
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["monthly_fee_hkd"], fee)
            self.assertEqual(rows[0]["broadband_speed_mbps"], "1000")
            self.assertEqual(rows[0]["contract_months"], contract_months)
            self.assertIn(segment, rows[0]["plan_name"])
            self.assertEqual(rows[0]["source_status"], "public_media_comparison_needs_review")

    def test_parse_icable_kennechu_2020_public_blog_row(self) -> None:
        source = {
            "source_id": "icable_kennechu_2020_home_broadband_guide",
            "brand": "i-CABLE",
            "product_category": "home_fibre_broadband",
            "url": "https://www.kennechu.info/2020/03/Broadband-Service-home.html",
            "period_label": "2020",
        }
        rows = _parse_page(source, {"status": 200, "text": ICABLE_KENNECHU_2020_TEXT}, "2026-07-03T00:00:00+08:00", "2020")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["plan_name"], "i-CABLE Broadband 1000M HK$98 36 months public blog market guide")
        self.assertEqual(rows[0]["monthly_fee_hkd"], "98")
        self.assertEqual(rows[0]["broadband_speed_mbps"], "1000")
        self.assertEqual(rows[0]["contract_months"], "36")
        self.assertEqual(rows[0]["source_status"], "public_blog_market_guide_needs_review")

    def test_parse_hgc_kennechu_2020_public_blog_row(self) -> None:
        source = {
            "source_id": "hgc_kennechu_2020_home_broadband_guide",
            "brand": "HGC",
            "product_category": "home_fibre_broadband",
            "url": "https://www.kennechu.info/2020/03/Broadband-Service-home.html",
            "period_label": "2020",
        }
        rows = _parse_page(source, {"status": 200, "text": ICABLE_KENNECHU_2020_TEXT}, "2026-07-07T00:00:00+08:00", "2020")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["plan_name"], "HGC Broadband 1000M HK$148 36 months public blog market guide")
        self.assertEqual(rows[0]["monthly_fee_hkd"], "148")
        self.assertEqual(rows[0]["broadband_speed_mbps"], "1000")
        self.assertEqual(rows[0]["contract_months"], "36")
        self.assertEqual(rows[0]["source_status"], "public_blog_market_guide_needs_review")

    def test_parse_icable_hkepc_2019_public_forum_row(self) -> None:
        source = {
            "source_id": "icable_hkepc_2019_forum_market_observation",
            "brand": "i-CABLE",
            "product_category": "home_fibre_broadband",
            "url": "https://www.hkepc.com/forum/viewthread.php?fid=12&page=5&tid=2484516",
            "period_label": "2019",
        }
        rows = _parse_page(source, {"status": 200, "text": ICABLE_HKEPC_2019_TEXT}, "2026-07-03T00:00:00+08:00", "2019")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["plan_name"], "i-CABLE Broadband 1000M HK$98 public forum market observation")
        self.assertEqual(rows[0]["monthly_fee_hkd"], "98")
        self.assertEqual(rows[0]["broadband_speed_mbps"], "1000")
        self.assertEqual(rows[0]["source_status"], "public_forum_market_observation_needs_review")

    def test_parse_hkbn_hkepc_2016_renewal_quote_row(self) -> None:
        source = {
            "source_id": "hkbn_hkepc_2016_1000m_248_renewal_quote",
            "brand": "HKBN",
            "product_category": "home_fibre_broadband",
            "url": "https://www.hkepc.com/forum/viewthread.php?extra=&fid=12&highlight=&page=514&tid=2053341",
            "period_label": "2016",
        }
        rows = _parse_page(source, {"status": 200, "text": HKBN_HKEPC_2016_RENEWAL_TEXT}, "2026-07-07T00:00:00+08:00", "2016")
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["plan_name"], "HKBN 1000M HK$248 24 months public forum renewal quote")
        self.assertEqual(row["monthly_fee_hkd"], "248")
        self.assertEqual(row["broadband_speed_mbps"], "1000")
        self.assertEqual(row["contract_months"], "24")
        self.assertEqual(row["customer_segment"], "renewal_quote_reference")
        self.assertEqual(row["source_status"], "public_forum_renewal_quote_needs_review")

    def test_parse_icable_2017_public_observation_rows(self) -> None:
        discuss_source = {
            "source_id": "icable_discuss_2017_forum_market_observation",
            "brand": "i-CABLE",
            "product_category": "home_fibre_broadband",
            "url": "https://www.discuss.com.hk/archiver/?tid-26638103.html=",
            "period_label": "2017",
        }
        apple_source = {
            "source_id": "icable_appledaily_2017_broadband_market_comparison",
            "brand": "i-CABLE",
            "product_category": "home_fibre_broadband",
            "url": "https://collection.news/appledaily/articles/HIYXCTNYJS2EW5SIIGINT5GXRA",
            "period_label": "2017",
        }
        discuss_rows = _parse_page(discuss_source, {"status": 200, "text": ICABLE_DISCUSS_2017_TEXT}, "2026-07-03T00:00:00+08:00", "2017")
        apple_rows = _parse_page(apple_source, {"status": 200, "text": ICABLE_APPLEDAILY_2017_TEXT}, "2026-07-03T00:00:00+08:00", "2017")
        self.assertEqual(len(discuss_rows), 1)
        self.assertEqual(discuss_rows[0]["monthly_fee_hkd"], "88")
        self.assertEqual(discuss_rows[0]["broadband_speed_mbps"], "200")
        self.assertEqual(discuss_rows[0]["source_status"], "public_forum_market_observation_needs_review")
        self.assertEqual(len(apple_rows), 1)
        self.assertEqual(apple_rows[0]["average_monthly_fee_hkd"], "140.7")
        self.assertEqual(apple_rows[0]["broadband_speed_mbps"], "1000")
        self.assertEqual(apple_rows[0]["source_status"], "public_media_archive_needs_review")

    def test_parse_icable_broadband_pro_2018_referral_case_row(self) -> None:
        source = {
            "source_id": "icable_broadband_pro_2018_referral_case",
            "brand": "i-CABLE",
            "product_category": "home_fibre_broadband",
            "url": "https://broadband-pro.weebly.com/case2.html",
            "period_label": "2018",
        }
        rows = _parse_page(source, {"status": 200, "text": ICABLE_BROADBAND_PRO_2018_TEXT}, "2026-07-03T00:00:00+08:00", "2018")
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["monthly_fee_hkd"], "88")
        self.assertEqual(row["broadband_speed_mbps"], "200")
        self.assertEqual(row["contract_months"], "30")
        self.assertEqual(row["source_status"], "public_referral_case_needs_review")
        self.assertIn("14/09/2018", row["evidence_excerpt"])

    def test_parse_icable_broadband_pro_2017_200m_144_referral_case_row(self) -> None:
        source = {
            "source_id": "icable_broadband_pro_2017_200m_144_referral_case",
            "brand": "i-CABLE",
            "product_category": "home_fibre_broadband",
            "url": "https://broadband-pro.weebly.com/case2.html",
            "period_label": "2017",
        }
        rows = _parse_page(source, {"status": 200, "text": ICABLE_BROADBAND_PRO_2017_200M_144_TEXT}, "2026-07-07T00:00:00+08:00", "2017")
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["monthly_fee_hkd"], "144")
        self.assertEqual(row["broadband_speed_mbps"], "200")
        self.assertEqual(row["contract_months"], "36")
        self.assertEqual(row["source_status"], "public_referral_case_needs_review")

    def test_parse_icable_broadband_pro_2016_referral_case_row(self) -> None:
        source = {
            "source_id": "icable_broadband_pro_2016_referral_case",
            "brand": "i-CABLE",
            "product_category": "home_fibre_broadband",
            "url": "https://broadband-pro.weebly.com/case2.html",
            "period_label": "2016",
        }
        rows = _parse_page(source, {"status": 200, "text": ICABLE_BROADBAND_PRO_2016_TEXT}, "2026-07-03T00:00:00+08:00", "2016")
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["average_monthly_fee_hkd"], "144")
        self.assertEqual(row["broadband_speed_mbps"], "200")
        self.assertEqual(row["contract_months"], "30")
        self.assertEqual(row["source_status"], "public_referral_case_needs_review")

    def test_parse_hkbn_broadband_pro_2017_referral_case_row(self) -> None:
        source = {
            "source_id": "hkbn_broadband_pro_2017_referral_case",
            "brand": "HKBN",
            "product_category": "home_fibre_broadband",
            "url": "https://broadband-pro.weebly.com/case2.html",
            "period_label": "2017",
        }
        rows = _parse_page(source, {"status": 200, "text": HKBN_BROADBAND_PRO_2017_TEXT}, "2026-07-03T00:00:00+08:00", "2017")
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["monthly_fee_hkd"], "248")
        self.assertEqual(row["broadband_speed_mbps"], "1000")
        self.assertEqual(row["contract_months"], "24")
        self.assertEqual(row["source_status"], "public_referral_case_needs_review")

    def test_parse_hgc_broadband_pro_2017_referral_case_is_source_gap(self) -> None:
        source = {
            "source_id": "hgc_broadband_pro_2017_referral_case",
            "brand": "HGC",
            "product_category": "home_fibre_broadband",
            "url": "https://broadband-pro.weebly.com/case2.html",
            "period_label": "2017",
        }
        rows = _parse_page(source, {"status": 200, "text": HGC_BROADBAND_PRO_2017_TEXT}, "2026-07-03T00:00:00+08:00", "2017")
        self.assertEqual(rows, [])

    def test_parse_hkbn_pay_tv_bundle_2019_rows(self) -> None:
        source = {
            "source_id": "hkbn_pay_tv_bundle_2019_mediaoutreach",
            "brand": "HKBN",
            "product_category": "home_fibre_broadband",
            "url": "https://www.media-outreach.com/news/hong-kong/2019/05/09/8713/hkbn-launches-mind-blowing-offer-to-all-pay-tv-customers/",
            "period_label": "2019",
        }
        rows = _parse_page(source, {"status": 200, "text": HKBN_PAY_TV_BUNDLE_2019_TEXT}, "2026-07-03T00:00:00+08:00", "2019")
        by_speed = {row["broadband_speed_mbps"]: row for row in rows}
        self.assertEqual(set(by_speed), {"100", "1000"})
        self.assertEqual(by_speed["100"]["monthly_fee_hkd"], "198")
        self.assertEqual(by_speed["1000"]["monthly_fee_hkd"], "238")
        self.assertTrue(all(row["source_status"] == "public_news_release_needs_review" for row in rows))
        self.assertTrue(all(row["monthly_fee_hkd"] != "588" for row in rows))

    def test_parse_hkbn_pay_tv_bundle_2019_official_pdf_rows(self) -> None:
        source = {
            "source_id": "hkbn_pay_tv_bundle_2019_official_pdf",
            "brand": "HKBN",
            "product_category": "home_fibre_broadband",
            "url": "https://reg.hkbn.net/WwwCMS/upload/pdf/en/20190509-HKBN-Launches-Mind-blowing-Offer-to-All-Pay-TV-Customers-EN-web.pdf",
            "period_label": "2019",
        }
        rows = _parse_page(source, {"status": 200, "text": HKBN_PAY_TV_BUNDLE_2019_TEXT}, "2026-07-03T00:00:00+08:00", "2019")
        by_speed = {row["broadband_speed_mbps"]: row for row in rows}
        self.assertEqual(by_speed["100"]["monthly_fee_hkd"], "198")
        self.assertEqual(by_speed["1000"]["monthly_fee_hkd"], "238")
        self.assertTrue(all(row["source_status"] == "parsed_official_pdf" for row in rows))

    def test_parse_hkbn_momax_2020_tc_pdf_crosscheck_rows(self) -> None:
        source = {
            "source_id": "hkbn_momax_smart_home_2020_pdf_tc",
            "brand": "HKBN",
            "product_category": "smart_home_bundle",
            "url": "https://reg.hkbn.net/WwwCMS/upload/pdf/tc/20201218_PressRelease_MOMAXxHKBN_TC_web.pdf",
            "period_label": "2020",
        }
        rows = _parse_page(source, {"status": 200, "text": HKBN_MOMAX_2020_TEXT}, "2026-07-03T00:00:00+08:00", "2020")
        by_fee = {row["monthly_fee_hkd"]: row for row in rows}
        self.assertEqual(set(by_fee), {"88", "68"})
        self.assertTrue(all(row["source_status"] == "parsed_official_pdf_tc" for row in rows))

    def test_parse_hgc_mytv_bundle_2021_official_pdf_row(self) -> None:
        source = {
            "source_id": "hgc_mytv_1g_2021_official_pdf",
            "brand": "HGC",
            "product_category": "home_fibre_broadband",
            "url": "https://www.hgc.com.hk/assets/images/2021_0426_ENG.pdf",
            "period_label": "2021",
        }
        rows = _parse_page(source, {"status": 200, "text": HGC_MYTV_BUNDLE_2021_TEXT}, "2026-07-03T00:00:00+08:00", "2021")
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["monthly_fee_hkd"], "198")
        self.assertEqual(row["broadband_speed_mbps"], "1000")
        self.assertEqual(row["contract_months"], "24")
        self.assertEqual(row["source_status"], "parsed_public_official_pdf")

    def test_parse_hkbn_oexbn_2026_official_api_rows(self) -> None:
        source = {
            "source_id": "hkbn_oexbn_2026_official_api",
            "brand": "HKBN",
            "product_category": "home_fibre_broadband",
            "url": "https://www.hkbn.net/personal/PurchaseFlow/GetAcqPlansByTag/en/oexbn",
            "period_label": "2026",
        }
        rows = _parse_page(source, {"status": 200, "text": HKBN_OEXBN_2026_API_TEXT}, "2026-07-03T00:00:00+08:00", "2026")
        by_speed = {row["broadband_speed_mbps"]: row for row in rows}
        self.assertEqual(by_speed["1000"]["monthly_fee_hkd"], "129")
        self.assertEqual(by_speed["1000"]["contract_months"], "36")
        self.assertEqual(by_speed["2500"]["monthly_fee_hkd"], "149")
        self.assertEqual(by_speed["2500"]["contract_months"], "24")
        self.assertTrue(all(row["source_status"] == "parsed_official_api" for row in rows))

    def test_parse_hkbn_iqiyi_2023_official_html_crosscheck(self) -> None:
        source = {
            "source_id": "hkbn_iqiyi_vip_2023_official",
            "brand": "HKBN",
            "product_category": "ott_value_added_service",
            "url": "https://www.hkbn.net/group/tc/newsroom/press-releases/20230802_iQIYI_HKBN",
            "period_label": "2023",
        }
        rows = _parse_page(source, {"status": 200, "text": HKBN_IQIYI_2023_TC_TEXT}, "2026-07-03T00:00:00+08:00", "2023")
        by_name = {row["plan_name"]: row for row in rows}
        self.assertEqual(len(rows), 2)
        self.assertEqual(by_name["HKBN iQIYI Gold VIP member monthly fee HK$38"]["monthly_fee_hkd"], "38")
        self.assertEqual(by_name["HKBN iQIYI Gold VIP member monthly fee HK$38"]["add_on_charges_hkd"], "10")
        self.assertEqual(by_name["HKBN iQIYI Diamond VIP member monthly fee HK$58"]["monthly_fee_hkd"], "58")
        self.assertEqual(by_name["HKBN iQIYI Diamond VIP member monthly fee HK$58"]["add_on_charges_hkd"], "18")

    def test_parse_hkbn_gigafast_tplink_2024_tc_official_crosscheck(self) -> None:
        source = {
            "source_id": "hkbn_gigafast_tplink_2024_official_tc",
            "brand": "HKBN",
            "product_category": "home_fibre_broadband",
            "url": "https://www.hkbn.net/group/tc/newsroom/press-releases/20241128-TPLink",
            "period_label": "2024",
        }
        rows = _parse_page(source, {"status": 200, "text": HKBN_GIGAFAST_TPLINK_2024_TC_TEXT}, "2026-07-03T00:00:00+08:00", "2024")
        by_name = {row["plan_name"]: row for row in rows}
        self.assertEqual(len(rows), 2)
        self.assertEqual(by_name["HKBN GigaFast 5Gbps / 10Gbps service starting HK$698"]["monthly_fee_hkd"], "698")
        self.assertEqual(by_name["HKBN existing customer GigaFast 5Gbps / 10Gbps upgrade additional HK$200"]["tariff_type"], "monthly_upgrade_fee")

    def test_parse_hkbn_fhkpuaa_2025_member_offer_rows(self) -> None:
        source = {
            "source_id": "hkbn_fhkpuaa_2025_member_offer_pdf",
            "brand": "HKBN",
            "product_category": "home_fibre_broadband",
            "url": "https://www.fhkpuaa.org.hk/image/data/FHKPUAA%20Cardholders%E2%80%99%20Special%20Offer%20%20Handbill_JAN25_ENG.pdf",
            "period_label": "2025",
        }
        rows = _parse_page(source, {"status": 200, "text": HKBN_FHKPUAA_2025_TEXT}, "2026-07-03T00:00:00+08:00", "2025")
        by_name = {row["plan_name"]: row for row in rows}
        self.assertEqual(by_name["HKBN 1000M Dual Home Broadband with Choice 1 of 4"]["monthly_fee_hkd"], "129")
        self.assertEqual(by_name["HKBN 2.5Gbps GigaFast Broadband 2500M Home Broadband"]["broadband_speed_mbps"], "2500")
        self.assertEqual(by_name["HKBN 5G Local Mobile Communication Service Plan 50GB"]["local_data_gb"], "50")
        self.assertEqual(by_name["HKBN 5G Local Mobile Communication Service Plan 50GB"]["post_fup_speed_mbps"], "1")
        self.assertTrue(all(row["source_status"] == "public_member_offer_pdf_needs_review" for row in rows))

    def test_parse_hkbn_hkis_2025_member_offer_rows(self) -> None:
        source = {
            "source_id": "hkbn_hkis_2025_member_offer_pdf",
            "brand": "HKBN",
            "product_category": "home_fibre_broadband",
            "url": "https://www.hkis.org.hk/uploads/editor/MemWelfare/202502_HKIS%20Members%20Special%20Offer%20Handbill_JAN25_ENG.pdf",
            "period_label": "2025",
        }
        text = HKBN_FHKPUAA_2025_TEXT.replace("FHKPUAA Cardholders", "HKIS Members")
        rows = _parse_page(source, {"status": 200, "text": text}, "2026-07-03T00:00:00+08:00", "2025")
        by_name = {row["plan_name"]: row for row in rows}
        self.assertEqual(by_name["HKBN 2000M Home Broadband with TP-Link Archer BE230 Wi-Fi 7 Router"]["monthly_fee_hkd"], "229")
        self.assertEqual(
            by_name["HKBN 2.5Gbps GigaFast Broadband with TP-Link Archer BE230 Wi-Fi 7 Router"]["monthly_fee_hkd"],
            "229",
        )
        self.assertTrue(all(row["source_id"] == "hkbn_hkis_2025_member_offer_pdf" for row in rows))

    def test_parse_hkbn_fhkpuaa_sep24_member_offer_rows(self) -> None:
        source = {
            "source_id": "hkbn_fhkpuaa_2024_sep_member_offer_pdf",
            "brand": "HKBN",
            "product_category": "home_fibre_broadband",
            "url": "https://www.fhkpuaa.org.hk/image/data/FHKPUAA%20Cardholders%E2%80%99%20Special%20Offer%20%20Handbill_Sep24_Eng.pdf",
            "period_label": "2024",
        }
        rows = _parse_page(source, {"status": 200, "text": HKBN_FHKPUAA_SEP24_TEXT}, "2026-07-03T00:00:00+08:00", "2024")
        by_name = {row["plan_name"]: row for row in rows}
        self.assertEqual(by_name["HKBN 1000M Dual Home Broadband with Choice 1 of 4"]["monthly_fee_hkd"], "129")
        self.assertEqual(by_name["HKBN 1000M Home Broadband with 4.5G 42Mbps 10GB mobile service"]["monthly_fee_hkd"], "159")
        self.assertEqual(by_name["HKBN 2.5Gbps GigaFast Broadband 2500M Home Broadband"]["broadband_speed_mbps"], "2500")
        self.assertNotIn("HKBN 5G Local Mobile Communication Service Plan 50GB", by_name)

    def test_parse_hkbn_mobile_launch_2016_skips_admin_fee_noise(self) -> None:
        source = {
            "source_id": "hkbn_mobile_launch_2016_prnewswire",
            "brand": "HKBN",
            "product_category": "mobile_consumer_4g",
            "url": "https://www.prnewswire.com/news-releases/hkbn-launches-all-new-mobiles-services-300326838.html",
            "period_label": "2016",
        }
        official_text = HKBN_MOBILE_LAUNCH_2016_TEXT.replace("Monthly fee [2] ", "")
        rows = _parse_page(source, {"status": 200, "text": official_text}, "2026-07-03T00:00:00+08:00", "2016")
        by_name = {row["plan_name"]: row for row in rows}
        fees = {row["monthly_fee_hkd"] for row in rows}
        self.assertEqual(by_name["HKBN Mobile Services Plan S HK$88 unlimited throttled data"]["post_fup_speed_mbps"], "0.384")
        self.assertEqual(by_name["HKBN Mobile Services Plan M HK$108 3GB"]["local_data_gb"], "3")
        self.assertEqual(by_name["HKBN Mobile Services Plan XL HK$248 6GB"]["local_data_gb"], "6")
        self.assertEqual(by_name["HKBN Quad-play free-to-go bundle from HK$248"]["tariff_type"], "monthly_bundle_fee_from")
        self.assertFalse(fees & {"18"})
        self.assertTrue(all(row["source_status"] == "parsed_public_news_release" for row in rows))

    def test_parse_hkbn_mobile_launch_2016_official_html_crosscheck(self) -> None:
        source = {
            "source_id": "hkbn_mobile_launch_2016_official_html",
            "brand": "HKBN",
            "product_category": "mobile_consumer_4g",
            "url": "https://reg.hkbn.net/WwwCMS/upload/web/en/Engagement-news-20160913-mobile-services-official-launch-web.html",
            "period_label": "2016",
        }
        rows = _parse_page(source, {"status": 200, "text": HKBN_MOBILE_LAUNCH_2016_TEXT}, "2026-07-03T00:00:00+08:00", "2016")
        self.assertEqual({row["source_status"] for row in rows}, {"parsed_official_html"})
        self.assertIn("HKBN Mobile Services Plan S HK$88 unlimited throttled data", {row["plan_name"] for row in rows})
        self.assertIn("HKBN Quad-play free-to-go bundle from HK$248", {row["plan_name"] for row in rows})

    def test_parse_hkbn_n_mobile_2023_tc_official_crosscheck(self) -> None:
        source = {
            "source_id": "hkbn_n_mobile_2023_official_tc",
            "brand": "HKBN",
            "product_category": "mobile_travel_lifestyle",
            "url": "https://www.hkbn.net/group/tc/newsroom/press-releases/20231206_Nmobile",
            "period_label": "2023",
        }
        rows = _parse_page(source, {"status": 200, "text": HKBN_N_MOBILE_2023_TC_TEXT}, "2026-07-03T00:00:00+08:00", "2023")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["monthly_fee_hkd"], "108")
        self.assertEqual(rows[0]["add_on_charges_hkd"], "18")

    def test_parse_hkbn_4g_mobile_bundle_2017_official_pdf_only_confirmed_78_plan(self) -> None:
        source = {
            "source_id": "hkbn_4g_mobile_bundle_2017_official_pdf",
            "brand": "HKBN",
            "product_category": "mobile_consumer_4g",
            "url": "https://reg.hkbn.net/WwwCMS/upload/pdf/en/HKBN%20Announces%20All-new%20Disruptive%204G%20Mobile%20Services%20Bundle_web.pdf",
            "period_label": "2017",
        }
        rows = _parse_page(source, {"status": 200, "text": HKBN_4G_MOBILE_BUNDLE_2017_TEXT}, "2026-07-03T00:00:00+08:00", "2017")
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["plan_name"], "HKBN 4G Mobile Services Bundle HK$78 5GB")
        self.assertEqual(row["monthly_fee_hkd"], "78")
        self.assertEqual(row["local_data_gb"], "5")
        self.assertEqual(row["source_status"], "parsed_public_official_pdf")

    def test_parse_hkbn_wifi_concierge_2017_official_rows(self) -> None:
        for source_id in [
            "hkbn_wifi_concierge_2017_official_html",
            "hkbn_wifi_concierge_2017_official_pdf_en",
            "hkbn_wifi_concierge_2017_official_pdf_tc",
        ]:
            with self.subTest(source_id=source_id):
                source = {
                    "source_id": source_id,
                    "brand": "HKBN",
                    "product_category": "home_telephone_wifi_bundle",
                    "url": "https://reg.hkbn.net/WwwCMS/upload/pdf/en/HKBN-Launches-All-new-Home-Telephone-and-Wi-Fi-Concierge-Service-EN-web.pdf",
                    "period_label": "2017",
                }
                rows = _parse_page(source, {"status": 200, "text": HKBN_WIFI_CONCIERGE_2017_TEXT}, "2026-07-07T00:00:00+08:00", "2017")
                self.assertEqual(len(rows), 1)
                row = rows[0]
                self.assertEqual(row["plan_name"], "HKBN Wi-Fi Concierge and Home Telephone Service Bundle HK$88")
                self.assertEqual(row["monthly_fee_hkd"], "88")
                self.assertEqual(row["contract_months"], "24/27")
                self.assertEqual(row["local_voice"], "Home Telephone service")
                self.assertEqual(row["broadband_speed_mbps"], "")
                self.assertEqual(row["tariff_type"], "monthly_bundle_fee")
                self.assertEqual(row["source_status"], "parsed_public_official_release")

    def test_parse_hkbn_4g_mobile_bundle_2018_chi_pdf_rows(self) -> None:
        source = {
            "source_id": "hkbn_4g_mobile_bundle_2018_pdf_chi",
            "brand": "HKBN",
            "product_category": "mobile_consumer_4g",
            "url": "https://reg.hkbn.net/WwwCMS/upload/pdf/tc/HKBN%20Delivers%20Bang%20for%20the%20Buck%20with%204G%20%2478month%20Mobile%20Bundle_CHI_web.pdf",
            "period_label": "2018",
        }
        rows = _parse_page(source, {"status": 200, "text": HKBN_4G_MOBILE_BUNDLE_2018_CHI_TEXT}, "2026-07-03T00:00:00+08:00", "2018")
        by_fee = {row["monthly_fee_hkd"]: row for row in rows}
        self.assertEqual(set(by_fee), {"78", "148", "218"})
        self.assertEqual(by_fee["148"]["local_data_gb"], "6")
        self.assertEqual(by_fee["218"]["local_data_gb"], "12")
        self.assertTrue(all(row["source_status"] == "parsed_public_official_pdf" for row in rows))

    def test_parse_hkbn_travel_pocket_wifi_2018_official_html_row(self) -> None:
        source = {
            "source_id": "hkbn_travel_pocket_wifi_2018_official_html",
            "brand": "HKBN",
            "product_category": "roaming_wifi",
            "url": "https://reg.hkbn.net/WwwCMS/upload/web/en/20180305_HKBN_announcements-web.html",
            "period_label": "2018",
        }
        rows = _parse_page(source, {"status": 200, "text": HKBN_TRAVEL_POCKET_WIFI_2018_HTML_TEXT}, "2026-07-03T00:00:00+08:00", "2018")
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["plan_name"], "HKBN Travel Pocket Wi-Fi HK$28/day additional day")
        self.assertEqual(row["monthly_fee_hkd"], "28")
        self.assertEqual(row["roaming_data_gb"], "0.5")
        self.assertEqual(row["post_fup_speed_mbps"], "0.128")
        self.assertEqual(row["source_status"], "parsed_official_html")

    def test_parse_hkbn_high_usage_mobile_2017_mediaoutreach_row(self) -> None:
        source = {
            "source_id": "hkbn_high_usage_mobile_2017_mediaoutreach",
            "brand": "HKBN",
            "product_category": "mobile_consumer_4g",
            "url": "https://www.media-outreach.com/news/hong-kong/2017/08/30/3859/hkbn-rolls-out-4-5g-full-speed-high-usage-mobile-bundles/",
            "period_label": "2017",
        }
        rows = _parse_page(source, {"status": 200, "text": HKBN_HIGH_USAGE_MOBILE_2017_TEXT}, "2026-07-03T00:00:00+08:00", "2017")
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["plan_name"], "HKBN 4G Mobile Services Bundle HK$218 12GB")
        self.assertEqual(row["monthly_fee_hkd"], "218")
        self.assertEqual(row["local_data_gb"], "12")
        self.assertEqual(row["source_status"], "public_news_release_needs_review")

    def test_parse_hkbn_68_10gb_2022_mobilemagazine_row(self) -> None:
        source = {
            "source_id": "hkbn_68_10gb_2022_mobilemagazine",
            "brand": "HKBN",
            "product_category": "mobile_consumer_5g",
            "url": "https://www.mobilemagazinehk.com/2022/02/10gb-5ghk68.html",
            "period_label": "2022",
        }
        rows = _parse_page(source, {"status": 200, "text": HKBN_68_10GB_2022_MOBILEMAGAZINE_TEXT}, "2026-07-03T00:00:00+08:00", "2022")
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["plan_name"], "HKBN 5G Mobile Offer HK$68 10GB")
        self.assertEqual(row["monthly_fee_hkd"], "68")
        self.assertEqual(row["local_data_gb"], "10")
        self.assertEqual(row["post_fup_speed_mbps"], "5")
        self.assertEqual(row["add_on_charges_hkd"], "18 admin fee waived")
        self.assertEqual(row["source_status"], "public_media_report_needs_review")

    def test_parse_hkbn_mobile_trial_2016_skips_sms_and_admin_fee_noise(self) -> None:
        source = {
            "source_id": "hkbn_mobile_trial_2016_pdf",
            "brand": "HKBN",
            "product_category": "mobile_consumer_4g",
            "url": "https://reg.hkbn.net/WwwCMS/upload/pdf/en/20160804_press_release_HKBNMobile_Services_E_final.pdf",
            "period_label": "2016",
        }
        rows = _parse_page(source, {"status": 200, "text": HKBN_MOBILE_TRIAL_2016_TEXT}, "2026-07-03T00:00:00+08:00", "2016")
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["monthly_fee_hkd"], "108")
        self.assertEqual(row["local_data_gb"], "3")
        self.assertEqual(row["add_on_charges_hkd"], "18 admin fee after waiver period")
        self.assertEqual(row["tariff_type"], "monthly_plan_fee")

    def test_parse_hkbn_enterprise_mobile_5g_current_page(self) -> None:
        source = {
            "source_id": "hkbn_enterprise_mobile_current",
            "brand": "HKBN",
            "product_category": "business_mobile_5g",
            "url": "https://www.hkbnes.com/web/sme/solutions/broadband/mobile-solutions/",
        }
        rows = _parse_page(source, {"status": 200, "text": HKBN_ENTERPRISE_MOBILE_5G_TEXT}, "2026-07-06T00:00:00+08:00", "current")
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["plan_name"], "HKBN Business 5G Mobile Services from HK$78")
        self.assertEqual(row["monthly_fee_hkd"], "78")
        self.assertEqual(row["tariff_type"], "business_mobile_5g_starting_monthly_fee")
        self.assertIn("starting as low as HK$78/month", row["add_on_charges_hkd"])

    def test_parse_hkbn_enterprise_mobile_5g_current_tc_page(self) -> None:
        source = {
            "source_id": "hkbn_enterprise_mobile_current_tc",
            "brand": "HKBN",
            "product_category": "business_mobile_5g",
            "url": "https://www.hkbnes.com/web/tc/sme/solutions/broadband/mobile-solutions/",
        }
        rows = _parse_page(source, {"status": 200, "text": HKBN_ENTERPRISE_MOBILE_5G_TC_TEXT}, "2026-07-06T00:00:00+08:00", "current")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["plan_name"], "HKBN Business 5G Mobile Services from HK$78")
        self.assertEqual(rows[0]["monthly_fee_hkd"], "78")

    def test_parse_hkbn_enterprise_mobile_4g_offer_skips_non_plan_fees(self) -> None:
        source = {
            "source_id": "hkbn_enterprise_mobile_4g_offer",
            "brand": "HKBN",
            "product_category": "business_mobile_4g",
            "url": "https://www.hkbnes.net/form/ec-quad-offer-en.jsp",
        }
        rows = _parse_page(source, {"status": 200, "text": HKBN_ENTERPRISE_MOBILE_4G_TEXT}, "2026-07-03T00:00:00+08:00", "current")
        by_name = {row["plan_name"]: row for row in rows}
        fees = {row["monthly_fee_hkd"] for row in rows}
        self.assertEqual(len(rows), 8)
        self.assertEqual(by_name["HKBN Enterprise Local 4G Plan HK$118 5GB"]["average_monthly_fee_hkd"], "98")
        self.assertEqual(by_name["HKBN Enterprise Local 4G Plan HK$138 3GB"]["local_voice"], "3000 local voice minutes")
        self.assertEqual(by_name["HKBN Enterprise Greater China 4G Plan HK$298 3GB"]["roaming_data_gb"], "3")
        self.assertEqual(by_name["HKBN Enterprise Greater China 4G Plan HK$358 6GB"]["add_on_charges_hkd"], "20/0.5GB extra data; 18 administration fee waived during contract period")
        self.assertFalse(fees & {"18", "0.3", "20", "30"})

    def test_parse_hkbn_enterprise_mobile_4g_offer_tc_rows(self) -> None:
        source = {
            "source_id": "hkbn_enterprise_mobile_4g_offer_tc",
            "brand": "HKBN",
            "product_category": "business_mobile_4g",
            "url": "https://www.hkbnes.net/form/ec-quad-offer-tc.jsp",
        }
        rows = _parse_page(source, {"status": 200, "text": HKBN_ENTERPRISE_MOBILE_4G_TC_TEXT}, "2026-07-06T00:00:00+08:00", "current")
        by_name = {row["plan_name"]: row for row in rows}
        fees = {row["monthly_fee_hkd"] for row in rows}
        self.assertEqual(len(rows), 8)
        self.assertEqual(by_name["HKBN Enterprise Local 4G Plan HK$118 5GB"]["average_monthly_fee_hkd"], "98")
        self.assertEqual(by_name["HKBN Enterprise Local 4G Plan HK$138 3GB"]["local_voice"], "3000 local voice minutes")
        self.assertEqual(by_name["HKBN Enterprise Greater China 4G Plan HK$298 3GB"]["roaming_data_gb"], "3")
        self.assertEqual(by_name["HKBN Enterprise Greater China 4G Plan HK$488 10GB"]["roaming_data_gb"], "10")
        self.assertFalse(fees & {"18", "20", "30"})

    def test_parse_hkbn_home_broadband_offer_rendered_snapshot_rows(self) -> None:
        source = {
            "source_id": "hkbn_home_broadband_offer",
            "brand": "HKBN",
            "product_category": "home_fibre_broadband",
            "url": "https://www.hkbn.net/personal/onlineexclusive/en/select-plan/oexbn",
        }
        rows = _parse_page(source, {"status": 200, "text": HKBN_OEXBN_RENDERED_TEXT}, "2026-07-03T00:00:00+08:00", "current")
        by_name = {row["plan_name"]: row for row in rows}
        self.assertEqual(by_name["HKBN 1000M Home Broadband Plan with 36-mth Home Telephone"]["monthly_fee_hkd"], "129")
        self.assertEqual(by_name["HKBN 1000M Home Broadband Plan with 36-mth Home Telephone"]["broadband_speed_mbps"], "1000")
        self.assertEqual(by_name["HKBN 2.5Gbps GigaFast Broadband Plan with 24-mth Home Telephone Service"]["monthly_fee_hkd"], "149")
        self.assertEqual(by_name["HKBN 2.5Gbps GigaFast Broadband Plan with 24-mth Home Telephone Service"]["broadband_speed_mbps"], "2500")
        waived_rows = {
            (row["average_monthly_fee_hkd"], row["contract_months"])
            for row in rows
            if row["plan_name"] == "HKBN 1000M Home Broadband Plan" and row["monthly_fee_hkd"] == "378"
        }
        self.assertEqual(waived_rows, {("302.4", "30"), ("336", "27")})
        self.assertTrue(all(row["source_status"] == "parsed_official_rendered_page_snapshot" for row in rows))

    def test_parse_smartone_kono_pdf_seed_rows(self) -> None:
        source = {
            "source_id": "smartone_kono_magazine_2019_pdf",
            "brand": "SmarTone",
            "product_category": "mobile_value_added_service",
            "url": "https://www.smartone.com/other/english/tc_V123_e.pdf",
            "period_label": "2019",
        }
        rows = _parse_page(source, {"status": 200, "text": SMARTONE_KONO_TEXT}, "2026-07-02T00:00:00+08:00", "2019")
        by_fee = {row["monthly_fee_hkd"]: row for row in rows}
        self.assertEqual(set(by_fee), {"36", "38"})
        self.assertEqual(by_fee["36"]["contract_months"], "24")
        self.assertTrue(all(row["source_status"] == "web_indexed_official_pdf_excerpt" for row in rows))

    def test_crawl_writes_expected_dataset_files(self) -> None:
        seen_clients = []

        def fake_fetch_page(_client, url, *, archive=False):
            seen_clients.append(_client)
            text = ICABLE_TEXT if "i-cable" in url else THREE_TEXT
            return {
                "url": url,
                "final_url": url,
                "status": 200,
                "content_type": "text/html",
                "bytes": len(text),
                "title": "fixture",
                "text": text,
                "error": "",
                "method": "fake",
            }

        import hk_competitor_product_crawl as crawler

        original_sources = crawler.CURRENT_SOURCES
        original_fetch = crawler.fetch_page
        try:
            crawler.CURRENT_SOURCES = [
                {
                    "source_id": "3hk_5g_sim_plan",
                    "brand": "3HK / Hutchison",
                    "product_category": "mobile_consumer_5g",
                    "url": "https://web.three.com.hk/plans/5g/index-en.html",
                },
                {
                    "source_id": "icable_broadband_offer",
                    "brand": "i-CABLE",
                    "product_category": "home_fibre_broadband",
                    "url": "https://www.i-cablebroadband-offer.com/",
                },
            ]
            crawler.fetch_page = fake_fetch_page
            with tempfile.TemporaryDirectory() as tmp:
                output_dir = Path(tmp)
                shared_client = object()
                status = crawl_competitor_products(output_dir=output_dir, client=shared_client)
                with (output_dir / "current_plans.csv").open(encoding="utf-8-sig") as fh:
                    rows = list(csv.DictReader(fh))
                with (output_dir / "source_gaps.csv").open(encoding="utf-8-sig") as fh:
                    gap_rows = list(csv.DictReader(fh))

            self.assertTrue(status["ok"])
            self.assertEqual(status["brands"], ["3HK / Hutchison", "i-CABLE"])
            self.assertEqual(status["source_count"], 2)
            self.assertTrue(seen_clients)
            self.assertTrue(all(client is shared_client for client in seen_clients))
            self.assertEqual(status["current_count"], 0)
            self.assertEqual(rows, [])
            self.assertTrue(any(row["brand"] == "i-CABLE" and row["gap_type"] == "single_source_unverified_plan_row" for row in gap_rows))
        finally:
            crawler.CURRENT_SOURCES = original_sources
            crawler.fetch_page = original_fetch

    def test_quality_audit_keeps_average_monthly_fee_for_review_rows(self) -> None:
        current_rows = []
        historical_rows = [
            {
                "period_label": "2017",
                "brand": "i-CABLE",
                "product_category": "home_fibre_broadband",
                "plan_name": "i-CABLE Home Broadband 1000M average HK$140.7 public media comparison",
                "monthly_fee_hkd": "",
                "average_monthly_fee_hkd": "140.7",
                "local_data_gb": "",
                "broadband_speed_mbps": "1000",
                "source_id": "icable_appledaily_2017_broadband_market_comparison",
                "source_status": "public_media_archive_needs_review",
                "verification_status": "single_source_needs_review",
            }
        ]
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            audit = _write_quality_audit(
                output_dir,
                current_rows,
                historical_rows,
                [],
                "2026-07-07T12:00:00+08:00",
            )
            markdown = (output_dir / "quality_audit.md").read_text(encoding="utf-8")

        self.assertEqual(audit["single_source_review_rows"][0]["average_monthly_fee_hkd"], "140.7")
        self.assertEqual(audit["unresolved_source_gap_count"], 0)
        self.assertEqual(audit["verification_backlog_count"], 0)
        self.assertIn("fee=140.7", markdown)

    def test_verification_does_not_merge_different_contract_terms(self) -> None:
        rows = [
            {
                "brand": "SmarTone",
                "product_category": "mobile_consumer_5g",
                "monthly_fee_hkd": "129",
                "average_monthly_fee_hkd": "",
                "local_data_gb": "30",
                "broadband_speed_mbps": "",
                "contract_months": "24",
                "service_generation": "5G",
                "tariff_type": "monthly_plan_fee",
                "plan_name": "SmarTone 5G Plan HK$129 30GB 24m",
                "source_id": "smartone_5g_listing_tc",
                "period_label": "2026",
            },
            {
                "brand": "SmarTone",
                "product_category": "mobile_consumer_5g",
                "monthly_fee_hkd": "129",
                "average_monthly_fee_hkd": "",
                "local_data_gb": "30",
                "broadband_speed_mbps": "",
                "contract_months": "30",
                "service_generation": "5G",
                "tariff_type": "monthly_plan_fee",
                "plan_name": "SmarTone 5G mobile plan comparison HK$129 30GB",
                "source_id": "smartone_quoquo_2026_mobile_plan_comparison",
                "period_label": "2026",
            },
        ]
        _apply_verification(rows)
        self.assertEqual([row["verification_count"] for row in rows], ["1", "1"])
        self.assertTrue(all(row["verification_status"] == "single_source_needs_review" for row in rows))

    def test_verification_allows_missing_contract_when_no_conflict(self) -> None:
        rows = [
            {
                "brand": "SmarTone",
                "product_category": "home_5g_broadband",
                "monthly_fee_hkd": "148",
                "average_monthly_fee_hkd": "",
                "local_data_gb": "unlimited",
                "broadband_speed_mbps": "",
                "contract_months": "",
                "service_generation": "5G",
                "tariff_type": "monthly_plan_fee",
                "plan_name": "SmarTone Home 5G Broadband HK$148",
                "source_id": "smartone_home_5g_launch_2020_pdf",
                "period_label": "2020",
            },
            {
                "brand": "SmarTone",
                "product_category": "home_5g_broadband",
                "monthly_fee_hkd": "148",
                "average_monthly_fee_hkd": "",
                "local_data_gb": "unlimited",
                "broadband_speed_mbps": "",
                "contract_months": "24",
                "service_generation": "5G",
                "tariff_type": "monthly_plan_fee",
                "plan_name": "SmarTone Home 5G Broadband HK$148",
                "source_id": "smartone_home_5g_2020_ezone_review",
                "period_label": "2020",
            },
        ]
        _apply_verification(rows)
        self.assertEqual([row["verification_count"] for row in rows], ["2", "2"])
        self.assertTrue(all(row["verification_status"] == "multi_source_or_multi_snapshot_verified" for row in rows))

    def test_verification_does_not_merge_public_and_private_segments(self) -> None:
        rows = [
            {
                "brand": "HGC",
                "product_category": "home_fibre_broadband",
                "monthly_fee_hkd": "119",
                "average_monthly_fee_hkd": "",
                "local_data_gb": "",
                "broadband_speed_mbps": "1000",
                "contract_months": "36",
                "service_generation": "Fibre/Broadband",
                "tariff_type": "public_third_party_broadband_comparison_reference",
                "customer_segment": "public_housing_reference",
                "plan_name": "HGC 1000M broadband public_housing_reference HK$119",
                "source_id": "hgc_yahoo_broadband_comparison_2026",
                "period_label": "2026",
            },
            {
                "brand": "HGC",
                "product_category": "home_fibre_broadband",
                "monthly_fee_hkd": "119",
                "average_monthly_fee_hkd": "",
                "local_data_gb": "",
                "broadband_speed_mbps": "1000",
                "contract_months": "36",
                "service_generation": "Fibre/Broadband",
                "tariff_type": "public_third_party_broadband_comparison_reference",
                "customer_segment": "private_building_reference",
                "plan_name": "HGC 1000M broadband private_building_reference HK$119",
                "source_id": "hgc_hktechreview_broadband_comparison_2025",
                "period_label": "2025",
            },
        ]
        _apply_verification(rows)
        self.assertEqual([row["verification_count"] for row in rows], ["1", "1"])
        self.assertTrue(all(row["verification_status"] == "single_source_needs_review" for row in rows))

    def test_verification_allows_generic_segment_when_no_segment_conflict(self) -> None:
        rows = [
            {
                "brand": "HGC",
                "product_category": "home_fibre_broadband",
                "monthly_fee_hkd": "109",
                "average_monthly_fee_hkd": "",
                "local_data_gb": "",
                "broadband_speed_mbps": "1000",
                "contract_months": "24",
                "service_generation": "Fibre/Broadband",
                "tariff_type": "public_media_broadband_comparison_reference",
                "customer_segment": "public_housing_reference",
                "plan_name": "HGC 1000M broadband public_housing_reference HK$109",
                "source_id": "hgc_hk01_public_housing_109_broadband_comparison_2026",
                "period_label": "2026",
            },
            {
                "brand": "HGC",
                "product_category": "home_fibre_broadband",
                "monthly_fee_hkd": "109",
                "average_monthly_fee_hkd": "",
                "local_data_gb": "",
                "broadband_speed_mbps": "1000",
                "contract_months": "24",
                "service_generation": "Fibre/Broadband",
                "tariff_type": "public_third_party_broadband_comparison_reference",
                "customer_segment": "market_reference",
                "plan_name": "HGC 1000M broadband market_reference HK$109",
                "source_id": "hgc_hk01_broadband_comparison_2026",
                "period_label": "2026",
            },
        ]
        _apply_verification(rows)
        self.assertEqual([row["verification_count"] for row in rows], ["2", "2"])
        self.assertTrue(all(row["verification_status"] == "multi_source_or_multi_snapshot_verified" for row in rows))

    def test_verification_prefers_structured_segment_over_mixed_evidence_excerpt(self) -> None:
        rows = [
            {
                "brand": "HKBN",
                "product_category": "home_fibre_broadband",
                "monthly_fee_hkd": "148",
                "average_monthly_fee_hkd": "",
                "local_data_gb": "",
                "broadband_speed_mbps": "2500",
                "contract_months": "36",
                "service_generation": "Fibre/Broadband",
                "tariff_type": "public_third_party_broadband_comparison_reference",
                "customer_segment": "private_building_reference",
                "plan_name": "HKBN 2500M broadband private_building_reference MoneyHero 2025 reference HK$148",
                "evidence_excerpt": "公屋參考價錢：HKBN 最低HK$109；私人樓宇指定 2.5Gbps GigaFast 寬頻計劃月費低至HK$148",
                "source_id": "hkbn_moneyhero_broadband_comparison_2025",
                "period_label": "2025",
            },
            {
                "brand": "HKBN",
                "product_category": "home_fibre_broadband",
                "monthly_fee_hkd": "148",
                "average_monthly_fee_hkd": "",
                "local_data_gb": "",
                "broadband_speed_mbps": "2500",
                "contract_months": "36",
                "service_generation": "Fibre/Broadband",
                "tariff_type": "public_third_party_broadband_offer_reference",
                "customer_segment": "private_building_reference",
                "plan_name": "HKBN 2500M broadband private_building_reference RoadshowOffer 2025 reference HK$148",
                "source_id": "hkbn_broadband_roadshowoffer_2500m_148_2025",
                "period_label": "2025",
            },
        ]
        _apply_verification(rows)
        self.assertEqual([row["verification_count"] for row in rows], ["2", "2"])
        self.assertTrue(all(row["verification_status"] == "multi_source_or_multi_snapshot_verified" for row in rows))

    def test_crawl_moves_single_source_rows_to_source_gaps(self) -> None:
        def fake_fetch_page(client, url):
            return {
                "url": url,
                "final_url": url,
                "status": 200,
                "content_type": "text/html",
                "bytes": len(MONEYSMART_BROADBAND_COMPARISON_2026_TEXT),
                "title": "fixture",
                "text": MONEYSMART_BROADBAND_COMPARISON_2026_TEXT,
                "error": "",
                "method": "fake",
            }

        import hk_competitor_product_crawl as crawler

        original_sources = crawler.CURRENT_SOURCES
        original_fetch = crawler.fetch_page
        try:
            crawler.CURRENT_SOURCES = [
                {
                    "source_id": "smartone_moneysmart_broadband_comparison_2026",
                    "brand": "SmarTone",
                    "product_category": "home_fibre_broadband",
                    "url": "https://blog.moneysmart.hk/zh-hk/credit-cards/broadband",
                    "period_label": "2026",
                }
            ]
            crawler.fetch_page = fake_fetch_page
            with tempfile.TemporaryDirectory() as tmp:
                output_dir = Path(tmp)
                crawl_competitor_products(output_dir=output_dir, client=object())
                with (output_dir / "historical_plans.csv").open(encoding="utf-8-sig") as fh:
                    historical_rows = list(csv.DictReader(fh))
                with (output_dir / "source_gaps.csv").open(encoding="utf-8-sig") as fh:
                    gap_rows = list(csv.DictReader(fh))
                audit = json.loads((output_dir / "quality_audit.json").read_text(encoding="utf-8"))

            self.assertEqual(historical_rows, [])
            self.assertEqual(audit["single_source_review_rows"], [])
            self.assertEqual(len(gap_rows), 5)
            self.assertEqual(audit["unresolved_source_gap_count"], 0)
            self.assertEqual(audit["verification_backlog_count"], 5)
            self.assertTrue(all(row["gap_type"] == "single_source_unverified_plan_row" for row in gap_rows))
            self.assertTrue(any(row["source_id"] == "smartone_moneysmart_broadband_comparison_2026" for row in gap_rows))
        finally:
            crawler.CURRENT_SOURCES = original_sources
            crawler.fetch_page = original_fetch


if __name__ == "__main__":
    unittest.main()
