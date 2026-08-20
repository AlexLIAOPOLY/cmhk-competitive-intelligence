import csv
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from hkt_product_crawl import (
    _parse_1010_infinite_entertainment,
    _parse_csl_2g_3g_4g_mobile_tariff_pdf,
    _parse_csl_1010_postpaid_mobile_tariff_pdf,
    _parse_csl_old_data_voice,
    _parse_pccw_mobile_2g_tariff,
    _parse_pccw_mobile_2g_99_tariff,
    _parse_1010_kingking_voice_roaming,
    _parse_1010_3g_mobile_tv,
    _parse_1010_football_service,
    _parse_1010_music_service,
    _parse_1010_anyplex,
    _parse_pccw_mobile_3g_tariff,
    _parse_pccw_mobile_cdma_service,
    _parse_pccw_mobile_concierge,
    _parse_pccw_mobile_other_3g_tariff,
    _parse_pccw_mobile_free_to_go_sim_only,
    _parse_pccw_mobile_multi_smart_sims,
    _parse_pccw_mobile_new_monthly_plan,
    _parse_pccw_mobile_netvigator_customer_offer,
    _parse_pccw_mobile_new_ultimate_smartphones,
    _parse_pccw_mobile_new_ultimate_tablets,
    _parse_pccw_mobile_tablet_data_tariff,
    _parse_pccw_mobile_ultimate_4g_smartphone,
    _parse_pccw_mobile_web_talk_tariff,
    _parse_csl_postpaid_service_plan_tariff_pdf,
    _parse_csl_smart_pama_tariff_pdf,
    _parse_hkt_business_broadband_tariff_pdf,
    _parse_hkt_customer_voice_hotline_tariff_pdf,
    _parse_hkt_datapak_private_circuit_tariff_pdf,
    _parse_hkt_enterprise_local_business_telephone,
    _parse_hkt_homephone_value_added_services,
    _parse_hkt_consumer_fixed_line_tariff_pdf,
    _parse_hkt_easywatch_commercial_tariff_pdf,
    _parse_hkt_eye_home_smartphone_tariff_pdf,
    _parse_hkt_eye_multimedia_service_tariff_pdf,
    _parse_hkt_international_toll_free_tariff_pdf,
    _parse_hkt_super_hotline_tariff_pdf,
    _parse_hkt_faxline_tariff_pdf,
    _parse_hkt_homefax_1_tariff_pdf,
    _parse_1010_ipad_pro_2020_product_page,
    _parse_hkt_eye_service_tariff_pdf,
    _parse_hkt_flexible_bandwidth_service_tariff_pdf,
    _parse_hkt_freedome_network_safety_tariff_pdf,
    _parse_hkt_home_easywatch_tariff_pdf,
    _parse_hkt_internet_access_tariff_pdf,
    _parse_hkt_integrated_digital_access_tariff_pdf,
    _parse_hkt_ip_voice_tariff_pdf,
    _parse_csl_voip_monthly_pass_tariff_pdf,
    _parse_hkt_ip_net_tariff_pdf,
    _parse_hkt_eye2_communication_package_tariff_pdf,
    _parse_hkt_local_business_telephone_tariff_pdf,
    _parse_hkt_megalink_service_tariff_pdf,
    _parse_hkt_megalink_plus_tariff_pdf,
    _parse_hkt_metro_ip_service_tariff_pdf,
    _parse_hkt_norton_secure_vpn_tariff_pdf,
    _parse_hkt_one_communications_tariff_pdf,
    _parse_hkt_premium_broadband_tariff_pdf,
    _parse_hkt_residential_cell_relay_tariff_pdf,
    _parse_hkt_severe_weather_warning_tariff_pdf,
    _parse_hkt_telecommunications_backup_tariff_pdf,
    _parse_hkt_sme_business_broadband,
    _parse_hkt_sme_5g_business_mobile,
    _parse_netvigator_csl_5g_home_internet,
    _parse_netvigator_list_price,
    _parse_source,
    crawl_hkt_products,
    OFFICIAL_TARIFF_DOCUMENT_SOURCES,
)


CSL_TEXT = """
5G Service Plan
Monthly Plan Fee (1) $348 Local data usage (2)(6) 100GB
Unlimited data (up to 2 Mbps) Mainland China & Macau roaming data usage (5) 3GB
Monthly Plan Fee (1) $398 Local data usage (2)(6) 150GB
Unlimited data (up to 2 Mbps) Mainland China & Macau roaming data usage (5) 3GB
"""

PCCW_MOBILE_3G_TEXT = """
3G tariff plan
PCCW mobile is dedicated to offering you the simplest and the most comprehensive tariff plans.
One 3G tariff plan meets all your needs Monthly fee Voice call mins Video call mins MMS SMS Local browsing
Normal Intra-network Intra-network Intra-network Intra-network
$138 600 MNP +400mins 600 60 60 Unlimited PCCW Channel Free
$198 2,000 2,000 200 200
$298 4,000 4,000 400 400
$498 10,000 10,000 1,000 1,000
Thereafter charge $0.8/min Intra-network: $1/min Local inter-network: $2/min
VAS included Voice mail, call forwarding, call hold, conference call, caller ID.
Monthly mobile service licence and related fee: $12
"""

PCCW_MOBILE_2G_99_TEXT = """
2G $99 Integrated Minutes Monthly Tariff Plan
PCCW mobile is dedicated to offering the most comprehensive 2G tariff plan.
Monthly fee Local voice call mins (Per Month) Thereafter charge (per min) VAS included
Peak Hour (08:00: - 21:00) (min) Off-Peak (21:00: - 08:00) (min)
$99 999 9,000 $1.0 12-month fee waiver of Voice Mail, Call Forwarding and Prime Features Pack
Monthly mobile service licence and related fee: $12
MNP customers can enjoy $300 rebate.
"""

PCCW_MOBILE_OTHER_3G_TEXT = """
Other 3G Tariff Plan
For only $98 per month
Plans optimize for fun and infotainment
For Fun Seekers For Web Surfers
Voice-call mins
3,000 Normal 2,000^ + Intra-network 1,000
1,600 Normal 1,000^+ Intra-network 600
Extra VAS
Free now-TV 300 mins
Free any one: Mobile Secretarial Service 30 Inter SMS 30MB Mobile Data Mobile MSN Unlimited Wi-Fi Connecting Tone
Free 100 MB mobileWeb + Unlimited Wi-Fi
Intra SMS Unlimited
VAS included Voice Mail, Call Forwarding, Conference Call, Caller ID and Call Waiting
Customers are required to pay monthly MTR/Tunnels/Mobile License/Adm Fee of $12
"""

PCCW_MOBILE_WEB_TALK_2010_TEXT = """
Web & Talk 月費計劃
月費 本地通話分鐘 數據用量(MB) 本地視像通話分鐘 本地多媒體訊息 本地瀏覽
$98 600 攜號轉台 +400分鐘 600 100 60 60 PCCW mobile 頻道：免費
$149 1,200 100 60 60
$199 1,600 200 100 100
$299 1,800 500 200 200
$399 3,000 無限 300 300
$478 4,000 攜號轉台 +400分鐘 4,000 無限 400 400
其後收費 $0.8/分鐘 每10MB為$10，最高收費$298(無限使用)
附送增值服務 智能留言信箱、來電轉駁、通話保留、會議通話、來電顯示、來電待接
註：每月流動電話服務牌照及有關費用：$12。客戶須簽12個月或以上服務合約
"""

PCCW_MOBILE_WEB_TALK_2012_TEXT = """
Web & Talk 月費計劃
月 費 攜指定手機上台 優惠月費 數據用量 + Wi-Fi 通話分鐘 視像通話分鐘 多媒體訊息 短訊 中港一卡兩號服務
$149 $99 100MB 無限及 Auto connect 功能 1,200 60 60 無限 -
$199 $116 200MB 1,600 100 100
$299 $160 500MB 1,800 200 200
$339 $199 5GB 1,800 200 200
$399 $232 無限 3,000 300 300
$478 $253.5 無限 8,000 (4,000+4,000) 攜號上台 +400 400 400
$499 $275 無限 4,000 400 400 200分鐘及優惠
攜機上台，適合任何手機型號！
月費 數據用量 + Wi-Fi 通話分鐘 視像通話分鐘 多媒體訊息 短訊
$98 100MB 無限及 Auto connect 功能 1,200 (600+600) 攜號上台+400 60 60 無限
$198 無限 1,200 (600+600) 攜號上台+400 60 60 無限
客戶須繳付每月港鐵/隧道/流動電話牌照/行政費$12
"""

PCCW_MOBILE_TABLET_DATA_TEXT = """
Tablet mobile data tariff plan
Monthly Fee Contract offer Local data usage Unlimited Local Wi-Fi Uplink/Downlink speed Contract period
$50 - Unlimited usage for 5 days Thereafter charge: $18/day Maximum: $288 12 months
$198 $300 Supermarket Coupon Unlimited Max downlink speed: 3.6Mbps Max uplink speed: 2.0Mbps 12 months
$328 $2200 rebate Unlimited Max downlink speed: 7.2Mbps Max uplink speed: 5.76Mbps 24 months
Customers are required to pay monthly mobile service license and related charges of $12
Unlimited services are provided subject to PCCW
"""

PCCW_MOBILE_FREE_TO_GO_TEXT = """
Free-to-go SIM Only Plan
Monthly fee $232* Data usage Unlimited Wi-Fi Unlimited and Auto Connect Voice call mins (Normal) 3,000
Free VAS uHub 25GB RoamSave roaming voice service free trial for 3 months HD now TV 300 mins on mobile
Customers are required to pay monthly mobile service license and related charges of $12.
Services are provided subject to PCCW mobile
"""

PCCW_MOBILE_NEW_MONTHLY_TEXT = """
New Monthly Plan
Mobile data monthly plan for smartphones
Handset subscription monthly fee SIM subscription special offer monthly fee Data usage Wi-Fi Voice call mins SMS MMS
$149 $98 100MB Unlimited and Auto Connect 1,800 60 Unlimited 60
$299 $169 800MB 3,000 200 200
$389 $182 5GB (Promotion offer) 2.5GB 3,000 300 300
Mobile data monthly plan for tablets
$119 - 100MB Unlimited and Auto Connect Unlimited 60
$269 $139 800MB 200
$359 $169 5GB (Promotion offer) 2.5GB 300
Customers must pay monthly MTR/ tunnel/ mobile service license and related charges of $12.
VAS included
"""

PCCW_MOBILE_ULTIMATE_4G_TEXT = """
Ultimate Mobility monthly plan for 4G smartphone
Mobile data monthly plan for smartphones
Handset subscription monthly fee $389 $429
SIM subscription special offer monthly fee $174 Free to go $199 $190 Free to go $238
Data usage Unlimited PCCW Wi-Fi 5GB 2.5GB 10GB 5GB
Voice call mins 3000 3000 SMS Unlimited Unlimited MMS 300 300 Video call mins 300 300
VAS included
"""

PCCW_MOBILE_MULTI_SMART_SIMS_TEXT = """
UTLIMATE MOBILITY Multi Smart SIMs monthly plan
SIM subecription Special monthly fee $268 Free-to-go
for 24-month contract no. of SIM 1 primary SIM and 2 secondary SIMs
Data usage Unlimited 5GB 2.5GB (Promotion offer) (Share among 3 SIMs)
Voice call mins 3000 video call mins 60 SMS unlimited MMS 300
Services are provided subject to PCCW mobile
"""

PCCW_MOBILE_2G_TARIFF_TEXT = """
2G tariff plan
Monthly fee Local voice call mins Per Month Thereafter charge VAS included
$88 1200 MNP +200 mins $1.0 12-month fee waiver of Voice Mail and Prime Features Package
Monthly mobile service license and related fee: $12
"""

PCCW_MOBILE_CDMA_TEXT = """
CDMA mobile service
PCCW mobile operates a CDMA2000 1xEVDO network providing mobile voice and data services in Hong Kong.
CDMA service plan Monthly fee Local voice call minutes Local mobile data service
$3,888 Unlimited Unlimited
VAS included Call Forwarding, Caller Number Display, Call Waiting and Call Hold
Notes: For new subscriptions, required prepayment of the first two months' monthly fee will be applied to settle the monthly fee for the first 2 months.
The minimum commitment period is 24 months.
"""

PCCW_MOBILE_CONCIERGE_TEXT = """
PCCW Concierge Tariff Plan
Monthly fee Data usage Voice call mins Video call mins MMS SMS
$149 100MB 1200 60 60 Unlimited
$199 200MB 1600 100 100 Unlimited
$249 500MB 1600 100 100 Unlimited
$299 500MB 1800 200 200 Unlimited
$399 Unlimited 3000 300 300 Unlimited
$478 Unlimited 8000 400 400 Unlimited
$499 China-HK 1-Card-2-Number 4000 400 400 Unlimited
Customers are required to pay monthly mobile service license and related charges of $12.
"""

PCCW_MOBILE_NETVIGATOR_CUSTOMER_TEXT = """
Special offer for Netvigator customer
Monthly fee Contract period Local data Unlimited Wi-Fi Optional add-on
$256 36 months 1GB Unlimited PCCW Wi-Fi
$288 30 months 1GB Unlimited PCCW Wi-Fi
$318 24 months 1GB Unlimited PCCW Wi-Fi
Upgrade data packages HK$20 4GB HK$50 Unlimited Voice upgrade HK$50
Local data usage charge
"""

PCCW_MOBILE_NEW_ULTIMATE_SMARTPHONES_TEXT = """
New Ultimate Mobility Service Plan for Smartphones
Handset subscription monthly fee $149 $299 $389 $429 $489
SIM subscription special monthly fee $119 $149 $174 $190 $238
Free-to-go smartphone offer $149 $169 $199 $238 $299
Data usage promotion 1GB 2.5GB 5GB 10GB 20GB
Standard entitlement 100MB 800MB 2.5GB 5GB 10GB
Voice call mins Unlimited SMS Unlimited MMS 60 200 300 300 300 Video call mins 60 200 300 300 300
VAS included
"""

PCCW_MOBILE_NEW_ULTIMATE_TABLETS_TEXT = """
New Ultimate Mobility Monthly Plan for Tablets
Handset subscription monthly fee $269 $359 $399 $459
SIM subscription special monthly fee $129 $148 $166 $215
Free-to-go tablet offer $208 $269
Data usage promotion 2.5GB 5GB 10GB 20GB
Standard entitlement 800MB 2.5GB 5GB 10GB
SMS Unlimited MMS 60 200 300 300
VAS included
"""

TEN_TEN_TEXT = """
Handset eVoucher offer Monthly 1 HK$459 FREE handset eVoucher worth HK$5,000
Local mobile data 2 150GB Unlimited (Max 2Mbps) 2
Monthly Mainland China & Macau roaming data usage 6 3GB 36 months
Unlimited local voice calling 4
Monthly 1 HK$299 Local mobile data 30GB Unlimited (Max 1Mbps) 2
Unlimited local voice call 4 Monthly Mainland China & Macau roaming data usage 6 1GB
Top-up Local Data: HK$10/2GB
"""

NETVIGATOR_INDEX_TEXT = """
Hot services Offers
1000M Fibre-to-the-Home Free Home Wi-Fi Service From HK$108 /month 36-month commitment Apply NOW
2500M Super Broadband Free Home Wi-Fi Service and Now TV Selected Pack Upgrade From HK$58 /month 36-month commitment Apply NOW
5G Home Internet From HK$168 /month 36-month commitment Apply NOW
"""

NETVIGATOR_CSL_5G_HOME_INTERNET_TEXT = """
csl x 網上行 5G 私「家」寬頻服務。月費 $168 / $198 服務計劃包括本地流動數據每月250GB，
其後均可繼續使用本地流動數據服務而不受速度限制。客戶須新上台選用指定 5G 私「家」寬頻服務及
簽訂指定承諾期，然而每月港幣 18 元行政費可獲豁免。
"""

NETVIGATOR_LIST_PRICE_TEXT = """
List prices for broadband service
Broadband Service - Enjoy unlimited usage and one NETVIGATOR Email Account
Service Plan Commitment Period Monthly Fee
50,000M Fiber-to-the-Home Service 24/36months HK$8,888
10,000M Fiber-to-the-Home Service 24 months HK$998
2500M + 1000M Multi-Use Broadband Service 24/36months HK$858
2500M Fiber-to-the-Home Service 24 months HK$818
2x1000M Multi-Use Broadband Service 24 months HK$798
1000M Fiber-to-the-Home Service (incl. LiKE1OO broadband service) 24 months HK$698
500M or below Fiber-to-the-Home / Basic Service (incl. LiKE1OO broadband service) 24 months HK$598
Promotional Offers Notes:
"""

NETVIGATOR_OLD_LIST_PRICE_TEXT = """
List prices for broadband service
Broadband Service – Enjoy unlimited usage and one NETVIGATOR Email Account
Service Plan Commitment Period Monthly Fee
10G Fiber-to-the-Home Service 24 months HK$2,888
4x1000M Multi-Use Broadband Service 24 months HK$998
2x1000M Multi-Use Broadband Service 24 months HK$798
1000M Fiber-to-the-Home Service 24 months HK$698
500M or below Fiber-to-the-Home / Basic Service 24 months HK$598
Promotional Offers Notes:
"""

HKT_INTERNET_ACCESS_TARIFF_2026_TEXT = """
Tariff No.: U0025-001-Jan2026-R Published on 6 January 2026
Name of Tariff: Internet Access Services (the "Services")
Current Services:
Service Monthly Fee
1.5M to 100M Basic Plan $700
2500M + 1000M / 2x1000M/4x1000M Multi-Use Broadband Service Plan $3,500
8M to 50,000M Fiber-to-the-home Plan $8,888
Additional NETVIGATOR Email Account $88/email account
The Services offer a wide range of dial-up and fixed broadband services.
"""

HKT_INTERNET_ACCESS_TARIFF_2015_TEXT = """
Tariff No.: U0025-003-Feb2015-R Published on 10 February 2015
Name of Tariff: Internet Access Services (the "Services")
Current Services:
Service Monthly Usage Fee
8M to 1000M and 10G Fiber-to-the-home Plan $3,500
1.5M to 100M Basic Plan $700
All plans include unlimited data consumption.
Legacy Services:
56K Dial-up Internet Services $298 Unlimited
Installation and activation charges apply separately.
"""

HKT_BUSINESS_BROADBAND_TARIFF_2016_TEXT = """
Business Broadband Services
Types of Services:
Class of Service Bandwidth Range Installation (HK$) Monthly Rental (HK$)
@WORK Broadband (Ultra Line, Single/Multi-Access) 1.5M/640K - 100M 1,000 2,500
@WORK Broadband ("Premier" Multi-Access) 1.5M/640K - 100M 1,000 4,000
@WORK Broadband (Business Broadband) / Ultra Broadband 1.5M - 1000M 1,000 3,000
Always-On Broadband 640K - 100M 1,500 35,000
Dedicated Internet 128K - 521K 8,000 12,000
Dedicated Internet T1 8,000 20,000
Dedicated Internet E1 8,000 35,000
Dedicated Internet 2M - 1000M 30,000 150,000
Metro-Internet 2M - 1000M 55,000 1,500,000
ATM Internet 2M - 60M 21,500 350,000
Terms and Conditions:
"""

HKT_PREMIUM_BROADBAND_TARIFF_2016_TEXT = """
Tariff No.: U0025-017-Nov2016-R Published on 30 November 2016
Name of Tariff: Premium Broadband Service
The tariffs are effective from 10 January 2017.
Monthly Rental
Premium Commercial Broadband Access Service client end
Asymmetric 10/100Base-T up to 8M Port 420 Bandwidth 14 per 1M
Asymmetric G.DMT up to 8M Port 380 Bandwidth 14 per 1M
Symmetric 10/100Base-T up to 4M Port 560 Bandwidth 70 per 1M
Higher than 4M and up to 10M Port 610 Bandwidth 65 per 1M
Higher than 10M and up to 20M Port 970 Bandwidth 55 per 1M
Higher than 20M and up to 100M Port 1,745 Bandwidth 165 per 10M
Premium Broadband Service Server End
OC-3c or FE up to 100M First 15 km 52,440 Additional 20 km 12,420 Additional 500 sessions 45,540
GE up to 1G First 15 km 120,060 Additional 20 km 13,800 Additional 500 sessions 45,540
Multiple Domain Name Monthly Rental 2,760 Installation 3,450 Deletion 3,450 Change 5,110
Premium Commercial Broadband VPN
Asymmetric 10/100Base-T up to 8M Port 1,390 Bandwidth 220 per 1M
Asymmetric G.DMT up to 8M Port 1,250 Bandwidth 220 per 1M
Symmetric 10/100Base-T up to 4M Port 1,660 Bandwidth 550 per 1M
Higher than 4M and up to 100M Port 3,470 Bandwidth 490 per 1M
Symmetric OC-3c up to 150M First 15 km 16,560 Additional 20 km 12,420 Bandwidth 2,760 per 10M
Symmetric GE up to 1G First 15 km 27,600 Additional 20 km 13,800 Bandwidth 6,210 per 50M
"""

HKT_METRO_IP_SERVICE_TARIFF_2019_TEXT = """
Tariff No.:U0025-005-Nov2019-R Published on 15 November 2019
Name of Tariff: Metro IP Service Packages
Tariff Table: Metro IP Service - Silver Plan (All in HK$)
Bandwidth Range (Mbps) Setup Rental/month Internal Relocation External Relocation Reconfiguration
512K~10Mbps $17,760 $20,000 $8,880 $17,760 $2,840
11~20 $53,280 $25,960 $26,640 $53,280 $2,840
901~1000 $133,200 $231,000 $66,600 $133,200 $2,840
Minimum Commitment Period for Silver plan is 12 months.
Tariff Table: Metro IP Service - Gold Plan (All in HK$)
Bandwidth Range (Mbps) Setup Rental/month Internal Relocation External Relocation Reconfiguration
1~10 $26,640 $33,000 $13,320 $26,640 $2,840
901~1000 $199,800 $428,400 $99,900 $199,800 $2,840
Minimum Commitment Period for Gold plan is 12 months
Tariff Table: Metro IP Service - Diamond Plan (All in HK$)
Bandwidth Range (Mbps) Setup Rental/month Internal Relocation External Relocation Reconfiguration
1~10 $26,640 $35,100 $13,320 $26,640 $2,840
901~1000 $199,800 $428,400 $99,900 $199,800 $2,840
Minimum Commitment Period for Diamond plan is 12 months
"""

HKT_FLEXIBLE_BANDWIDTH_TARIFF_2019_TEXT = """
U0025-001-Jan2019-R Published on 31 Jan 2019
Name of Tariff: Flexible Bandwidth Service
1.3 Charges
1.3.1 One-off Charges per End
Installation 15,000 Internal Relocation 15,000 External Relocation 15,000
1.3.2 Monthly Recurrent Charges
Point-to-Multipoint Service Charges per End (HK$)
Server End :
1 - 50 Mbps 15,000
51 - 100 Mbps 25,000
501 - 1,000 Mbps (GE interface) 51,000
5,001 - 10,000 Mbps 450,000
Client End :
1 Mbps 3,600
10 Mbps 9,000
501 - 1,000 Mbps (GE interface) 50,000
Point-to-Point Service Charges per End (HK$)
1 Mbps 3,600
1000 Mbps 50,000
10 Gbps 450,000
100 Gbps 1,500,000
1.3.3 Diversity Option
Additional Monthly Recurrent Charges 7,400 Additional One-off Installation Charges 3,150
"""

HKT_MEGALINK_TARIFF_2013_TEXT = """
Tariff No.: U0025-034-Dec2013-R Published on 9 December 2013
Name of Tariff: MegaLink Service
Tariff Table (effective from 10 January 2014):
A. MegaLink Access Client End (CE) Service All in HK$
Bandwidth Range Monthly Rental Installation Internal Relocation External Relocation Reconfiguration
Asymmetric - 10Base-T bridging or ATM-25 Up to 8M
1.5M : $380
6M : $435
8M : $459
Asymmetric - 10Base-T routing Up to 6M
1.5M : $474
6M : $490
Asymmetric - G.DMT Up to 8M
1.5M : $344
6M : $399
8M : $423
Symmetric - 10Base-T Up to 2M
2M : $765
Installation $1,610 Internal Relocation $690 External Relocation $1,150 Reconfiguration $690
B. MegaLink Access Server End (SE) Service All in HK$
Server End - OC-3c or FE Up to 100M
First 15 km : $57,820
Additional 20 km : $12,240
Additional 500: $45,890 sessions
Multiple Domain Name Per additional domain name per server end $3,060
C. MegaLink VPN Client End (CE) Service All in HK$
Asymmetric - 10Base-T or ATM-25 Up to 6M
1.5M : $1,910
3M : $2,220
4.5M : $2,370
6M : $2,880
Asymmetric - G.DMT Up to 6M
1.5M : $1,530
3M : $1,910
4.5M : $2,070
6M : $2,570
Symmetric - 10/100Base-T Up to 25M
2M : $2,750
4M : $4,280
6M : $6,820
10M : $9,300
25M : $16,050
D. MegaLink VPN Server End (SE) Service All in HK$
Symmetric - OC-3c Up to 150M
First 15 km : $17,600
Additional 20 km : $12,240
Bandwidth : $2,600 per 10M
Symmetric - GE Up to 1G
First 15 km : $31,350
Additional 20 km : $12,240
Bandwidth : $6,500 per 50M
The Services are subject to applicable terms and conditions.
Minimum Commitment Period for each circuit of the Services is 12 months.
"""

HKT_MEGALINK_TARIFF_2012_TEXT = """
Tariff No.: U025-006-Jul2012-R Published on 3 July 2012
Name of Tariff: MegaLink Service
Tariff Table:
A. MegaLink Access Client End (CE) Service All in HK$
Monthly Rental
Asymmetric - 10Base-T bridging or ATM-25 Up to 8M
1.5M : $330
6M : $378
8M : $399
Asymmetric - 10Base-T routing Up to 6M
1.5M : $412
6M : $426
Asymmetric - G.DMT Up to 8M
1.5M : $299
6M : $347
8M : $368
Symmetric - 10Base-T Up to 2M
2M : $665
B. MegaLink Access Server End (SE) Service All in HK$
Server End - OC-3c or FE Up to 100M
First 15 km : $50,274
Additional 20 km : $10,640
Additional 500: $39,900 sessions
Multiple Domain Name Per additional domain name per server end $2,660
C. MegaLink VPN Client End (CE) Service All in HK$
Asymmetric - 10Base-T or ATM-25 Up to 6M
1.5M : $1,663
3M : $1,930
4.5M : $2,060
6M : $2,500
Asymmetric - G.DMT Up to 6M
1.5M : $1,330
3M : $1,660
4.5M : $1,800
6M : $2,235
Symmetric - 10/100Base-T Up to 25M
2M : $2,390
4M : $3,725
6M : $5,930
10M : $8,090
25M : $13,960
D. MegaLink VPN Server End (SE) Service All in HK$
Symmetric - OC-3c Up to 150M
First 15 km : $15,300
Additional 20 km : $10,640
Bandwidth : $2,260 per 10M
Symmetric - GE Up to 1G
First 15 km : $27,260
Additional 20 km : $10,640
Bandwidth : $5,650 per 50M
The Services are subject to applicable terms and conditions.
Minimum Commitment Period for each circuit of the Services is 12 months.
"""

HKT_MEGALINK_TARIFF_2016_TEXT = """
Tariff No.: U0025-016-Nov2016-R Published on 30 November 2016
Name of Tariff: MegaLink Service
Annex A is to take effect from 10 January 2017.
Tariff Table (effective from 10 January 2017):
A. MegaLink Access Client End (CE) Service All in HK$
Bandwidth Range Monthly Rental Installation Internal Relocation External Relocation Reconfiguration
Asymmetric - 10Base-T bridging or ATM-25 Up to 8M
1.5M : $460
6M : $530
8M : $560
Asymmetric - 10Base-T routing Up to 6M
1.5M : $570
6M : $590
Asymmetric - G.DMT Up to 8M
1.5M : $420
6M : $480
8M : $510
Symmetric - 10Base-T Up to 2M
2M : $920
Installation $1,940 Internal Relocation $830 External Relocation $1,380 Reconfiguration $830
B. MegaLink Access Server End (SE) Service All in HK$
Server End - OC-3c or FE Up to 100M
First 15 km : $69,390
Additional 20 km : $14,690
Additional 500: $55,070 Sessions
Multiple Domain Name Per additional domain name per server end $3,680
C. MegaLink VPN Client End (CE) Service All in HK$
Asymmetric - 10Base-T or ATM-25 Up to 6M
1.5M : $2,300
3M : $2,670
4.5M : $2,850
6M : $3,460
Asymmetric - G.DMT Up to 6M
1.5M : $1,840
3M : $2,300
4.5M : $2,490
6M : $3,090
Symmetric - 10/100Base-T Up to 25M
2M : $3,300
4M : $5,140
6M : $8,190
10M : $11,160
25M : $19,260
D. MegaLink VPN Server End (SE) Service All in HK$
Symmetric - OC-3c Up to 150M
First 15 km : $21,120
Additional 20 km : $14,690
Bandwidth : $3,120 per 10M
Symmetric - GE Up to 1G
First 15 km : $37,620
Additional 20 km : $14,690
Bandwidth : $7,800 per 50M
The Services are subject to applicable terms and conditions.
Minimum Commitment Period for each circuit of the Services is 12 months.
"""

HKT_MEGALINK_TARIFF_2023_TEXT = """
Tariff No.: U0025-005-Sep2023-R Published on 19 September 2023
Name of Tariff: MegaLink Service
Effective date of tariff: 19 September 2023
A. MegaLink Access Client End (CE) Service All in HK$
Monthly Rental
Asymmetric - 10Base-T bridging or ATM-25 Up to 8M
1.5M : $380
6M : $435
8M : $459
Asymmetric - 10Base-T routing Up to 6M
1.5M : $474
6M : $490
Asymmetric - G.DMT Up to 8M
1.5M : $344
6M : $399
8M : $423
Symmetric - 10Base-T Up to 2M
2M : $765
B. MegaLink Access Server End (SE) Service All in HK$
Server End - OC-3c or FE Up to 100M
First 15 km : $57,820
Additional 20 km : $12,240
Additional 500: $45,890 sessions
Multiple Domain Name Per additional domain name per server end $3,060
C. MegaLink VPN Client End (CE) Service All in HK$
Asymmetric - 10Base-T or ATM-25 Up to 6M $20,000
Asymmetric - G.DMT Up to 6M $20,000
Symmetric - 10/100Base-T Up to 25M
2M : $10,000
4M : $15,000
6M : $20,000
10M : $30,000
25M : $50,000
D. MegaLink VPN Server End (SE) Service All in HK$
Symmetric - OC-3c Up to 150M
First 15 km : $17,600
Additional 20 km : $12,240
Bandwidth : $2,600 per 10M
Symmetric - GE Up to 1G
First 15 km : $31,350
Additional 20 km : $12,240
Bandwidth : $6,500 per 50M
The Services are subject to applicable terms and conditions.
Minimum Commitment Period for each circuit of the Services is 12 months.
"""

HKT_DATAPAK_TARIFF_2013_TEXT = """
Tariff No.: U0025-031-Nov2013-R Published on 5 November 2013
Name of Tariff: Datapak Services and Private Circuit Service
4. Datapak Fiberline Service
Service Description Monthly Rental HK$/end Installation/External Removal HK$/end Internal Removal HK$/end
4.1 Fiberline Service
Fast Ethernet 18,800.0 12,000.0 9,000.0
Ethernet Private Line (50M) 12,000.0 12,000.0 7,000.0
Ethernet Private Line (30M) 10,200.0 12,000.0 7,000.0
Ethernet Private Line (20M) 9,300.0 9,300.0 5,000.0
Ethernet Private Line (15M) 8,625.0 9,300.0 5,000.0
Ethernet Private Line (10M) 7,950.0 9,300.0 5,000.0
Gigabit Ethernet 68,000.0 50,000.0 30,000.0
Fibre Channel 1G 68,000.0 50,000.0 30,000.0
Fibre Channel 2G 78,000.0 50,000.0 30,000.0
Fibre Channel 4G 88,000.0 50,000.0 30,000.0
10 Gigabit Ethernet 140,000.0 100,000.0 60,000.0
STM1/OC3 52,000.0 45,000.0 22,500.0
T3 29,325.0 25,000.0 12,500.0
Fiberline Connect 25,000.0 66,600.0 22,200.0
Fiberline Connect (for 31 links & above) N/A 56,610.0 N/A
Fiberline FDDI 13,250.0 14,430.0 8,140.0
Fiberline Coupling 40,000.0 45,000.0 15,000.0
Fiberline Cellular Dual Band (2-Fibre) 16,000.0 25,000.0 6,000.0
Fiberline Cellular Dual Band (3-fibre) 20,000.0 30,000.0 8,000.0
4.2 Fiberline DWDM (Note 1& 2)
- 4 Interfaces and bandwidth of 2.5G 70,000.0 118,400.0 (per location) 74,000.0
- Additional Interface and Bandwidth of 1.25G 5,000.0 11,840.0 7,400.0
4.3 Fiberline CWDM (Note 1& 2)
- First 2 Interfaces 40,000.0 74,000.0 44,400.0
- Additional Interface 5,000.0 7,400.0 (per location) 4,400.0
Remarks for Datapak Fiberline Service:
9. Internal Leased Circuit
Service Description Monthly Rental HK$/end Installation HK$/end External Removal HK$/end Internal Removal HK$/end
9.1 Private circuit within the same building
2-wire 117.8 592.0 N/A 592.0
4-wire 245.8 592.0 N/A 592.0
Note for Internal Leased Circuit:
"""

HKT_DATAPAK_TARIFF_2023_TEXT = """
Tariff No.: U0025-004-Sep2023-R Published on 15 September 2023
Name of Tariff: Datapak Services and Private Circuit Service
4. Datapak Fiberline Service
Service Description Monthly Rental HK$/end Installation/External Removal HK$/end Internal Removal HK$/end
4.1 Fiberline Service
Fast Ethernet 18,800.0 24,000.0 18,000.0
Ethernet Private Line (50M) 12,000.0 24,000.0 14,000.0
Ethernet Private Line (30M) 10,200.0 24,000.0 14,000.0
Ethernet Private Line (20M) 9,300.0 18,600.0 10,000.0
Ethernet Private Line (15M) 8,625.0 18,600.0 10,000.0
Ethernet Private Line (10M) 7,950.0 18,600.0 10,000.0
Gigabit Ethernet 68,000.0 50,000.0 30,000.0
Gigabit Ethernet (200M) 28,200.0 50,000.0 30,000.0
Fibre Channel 1G 68,000.0 50,000.0 30,000.0
Fibre Channel 2G 78,000.0 50,000.0 30,000.0
Fibre Channel 4G 88,000.0 50,000.0 30,000.0
10 Gigabit Ethernet 140,000.0 100,000.0 60,000.0
STM1/OC3 70,000.0 90,000.0 45,000.0
T3 29,325.0 50,000.0 25,000.0
Channelized T3 43,000.0 37,000.0 19,980.0
Multi-Drop T3 43,000.0 37,000.0 19,800.0
Fiberline Connect 25,000.0 66,600.0 22,200.0
Fiberline Connect (for 31 links & above) N/A 56,610.0 N/A
Fiberline FDDI 13,250.0 28,860.0 16,280.0
Fiberline Coupling 40,000.0 45,000.0 15,000.0
Fiberline Cellular Dual Band (2-Fibre) 16,000.0 25,000.0 6,000.0
Fiberline Cellular Dual Band (3-fibre) 20,000.0 30,000.0 8,000.0
Fiberline Wavelength 1 18,800.0 24,000.0 18,000.0
4.2 Fiberline DWDM (Note 1& 2)
- 4 Interfaces and bandwidth of 2.5G 70,000.0 118,400.0 (per location) 74,000.0
- Additional Interface and Bandwidth of 1.25G 5,000.0 11,840.0 7,400.0
4.3 Fiberline CWDM (Note 1& 2)
- First 2 Interfaces 40,000.0 74,000.0 44,400.0
- Additional Interface 5,000.0 7,400.0 (per location) 4,400.0
Remarks for Datapak Fiberline Service:
9. Internal Leased Circuit
Service Description Monthly Rental HK$/end Installation HK$/end External Removal HK$/end Internal Removal HK$/end
9.1 Private circuit within the same building
2-wire 215.0 592.0 N/A 592.0
4-wire 446.0 592.0 N/A 592.0
Note for Internal Leased Circuit:
"""

HKT_TELECOMMUNICATIONS_BACKUP_TARIFF_2013_TEXT = """
Tariff No.: U0025-024-Jun2013-R Published on 1 June 2013
Name of Tariff: Telecommunications Backup Service for Commercial Customers
Rates:
(1) Continuity Plan and Smartline iBCP
Charge for a Continuity Plan Configuration
(a) Set-up charge
(i) 1-50 Lines HK$5,500
(b) Monthly Charge
(i) 1-50 Lines HK$2,500
(ii) 51-100 Lines HK$3,000
(iii) 101-200 Lines HK$4,000
(iv) 201-300 Lines HK$6,000
(v) Thereafter every HK$2,000 additional 100 Lines
(2) IDA-P Mutual Backup Service
(a) Set-up charge: HK$1,500 / IDA-P Line
(b) Monthly charge: HK$2,000 / IDA-P Line
(3) Smartline iBCP
(a) Set-up charge
(i) 1-25 Lines HK$5,000
(ii) 26-50 Lines HK$8,000
(b) Monthly Charge
(i) 1-25 Lines HK$5,000
(ii) 26-50 Lines HK$6,000
(iii) Thereafter every HK$6,000 additional 25Lines
Remarks:
"""

HKT_ONE_COMMUNICATIONS_TARIFF_2011_TEXT = """
Tariff No.: U025-031 Published on 8 July 2011
Name of Tariff: one communications
Monthly Service List of the user plans available Charges (HK$)
A. Staff (includes voice and broadband* service): $258/user/month
B. Executive (Staff user plan with FMC features): $298/user/month
C. Boss/Secretary (Executive user plan with Boss/Sec): $398/user/month
D. Boss (Lite)/Secretary (Lite) (Executive user plan with Boss/Sec): $368/user/month
E. Operator (Boss/Secretary user plan with operator features): $638/user/month
F. Enterprise Centrex - Executive (1:1) $238/user/month
G. Enterprise Centrex - Boss/Secretary (1:1) $338/user/month
H. Enterprise Centrex - Boss (Lite)(1:1)/Secretary (Lite) (1:1) $308/user/month
I. Enterprise Centrex - Operator (1:1) $578/user/month
J. Enterprise Centrex - Executive (1:3) : $208/user/month
K. Enterprise Centrex - Boss/Secretary (1:3) $308/user/month
L. Enterprise Centrex - Boss (Lite)(1:3)/Secretary (Lite) (1:3) $278/user/month
M. Enterprise Centrex - Operator (1:3) $548/user/month
FMC features: $98/user/month Office Anywhere features: $98/user/month Multi-site intercom connection fee: $100/site/month
"""

HKT_EYE_SERVICE_TARIFF_2014_TEXT = """
Tariff No.: U0025-012-May2014-R Published on 16 May 2014
Name of Tariff: eye Service ("Service")
The table below sets out the charges for each of the Service:
Features Particulars Charges (HK$)
eye Service core service charge
(a) voice call; (b) access to various Infotainment Services; (c) SMS; and (d) local video call.
(new customers are required to subscribe to the Service with a designated commitment period)
888 per month
Short Message Service - in text format Local SMS 0.5 / SMS Fixed-to-Mobile 1.0 / SMS International SMS 1.5 / SMS
"""

HKT_EYE_COMMUNICATION_PACKAGE_TARIFF_2013_TEXT = """
Tariff No.: U0025-013-May2013-R Published on 30 May 2013
Name of Tariff: eye Communication Package ("Service")
The table below sets out the charges for each of the Service:
Features Particulars Charges (HK$)
eye Communication Package core service charge
(a) voice call; (b) access to various Infotainment Services; (c) SMS; and (d) local video call.
888 per month
Local SMS 0.5 / SMS Fixed-to-Mobile 1.0 / SMS International SMS 1.5 / SMS
Connection charge 680
"""

HKT_CUSTOMER_VOICE_HOTLINE_TARIFF_2013_TEXT = """
Tariff No.: U0025-017-Jun2013-R Published on 1 June 2013
Name of Tariff: Customer Voice Hotline Management Service ("Service")
Customer Voice Hotline Management Service provides dedicated telephone numbers and one or more value-added services.
Rates for the Service (except Call Queue):
Setup charge: HK$32,000
Monthly charge: HK$2,500 on a per port/user and/or per telephone line basis
Rates for Call Queue:
Setup/installation charge: HK$2,000
Monthly charge: HK$2,800/call queue HK$1,000/user
Other service-feature and call charges apply separately.
"""

HKT_RESIDENTIAL_CELL_RELAY_TARIFF_2013_TEXT = """
Tariff No.: U0025-022-Jun2013-R Published on 1 June 2013
Name of Tariff: Residential Cell Relay Services (CRS)
CRS Customer Access (CRS CA) Service C. CRS Service Provider End Service.
Asymmetric 10Base-T single session: 1.5M $150; 3M $158; 6M $166; 8M $171.
Asymmetric G.DMT single session: 1.5M $110; 3M $118; 6M $126; 8M $131.
Asymmetric 10Base-T up to 4 sessions: 3M $171; 6M $179; 8M $184.
Asymmetric G.DMT up to 4 sessions: 3M $128; 6M $136; 8M $141.
CRS SP 155M first 15km $15,000. CRS SP-FE 100M first 15km $34,500.
CRS SP-GE 1000M first 15km $78,000. Multiple Domain Name per server end $2,000.
Installation, internal relocation, external relocation and reconfiguration charges apply separately.
"""

HKT_MEGALINK_PLUS_TARIFF_2013_TEXT = """
Tariff No.: U0025-011-May2013-R Published on 14 May 2013
Megalink Plus is a commercial VPN service over a shared IP infrastructure.
Megalink Plus Host End: 1-10M Monthly Rental $22,100; 11-45M Monthly Rental $58,500;
50-500M Monthly Rental $123,500; 550-1000M Monthly Rental $162,500.
Megalink Plus Client End: Asymmetric up to 8M/640K Monthly Rental $5,000;
Symmetric up to 10M/10M Monthly Rental $10,000. Setup, relocation and reconfiguration charges apply separately.
"""

HKT_MEGALINK_PLUS_TARIFF_2008_TEXT = """
Tariff No.: F050-0007 Published on 28 November 2008. Megalink Plus.
Host End 2M Monthly Rental $5,000; 3M $6,500; 4M $8,000; 6M $11,000; 8M $14,000; 10M $17,000;
15M $20,000; 20M $25,000; 25M $30,000; 30M $35,000; 40M $40,000; 50M $45,000; 100M $55,000.
Client End 1.5M/640K Monthly Rental $1,500; 6M/640K $2,000; 2M/2M $3,000.
Installation, internal relocation, external relocation and reconfiguration charges are separate.
"""

HKT_IP_NET_TARIFF_2013_TEXT = """
Tariff No.: U0025-004-Mar2013-R Published on 20 March 2013. IP-Net is a single port solution.
Bandwidth Range (Mbps) 1-10 Monthly Rental $9,100; 11-20 $14,300; 25-30 $18,200; 35-40 $22,100;
45-50 $24,700; 55-60 $28,600; 65-70 $32,500; 75-80 $35,100; 85-90 $39,000; 95-100 $42,900;
150-200 $57,200; 250-300 $67,600; 350-400 $79,300; 450-500 $91,000; 550-600 $102,700;
650-700 $114,400; 750-800 $124,800; 850-900 $136,500; 950-1000 $148,200.
Setup, internal relocation, external relocation and reconfiguration are separate charges.
"""

HKT_HOME_EASYWATCH_TARIFF_2013_TEXT = """
Tariff No.: U0025-005-Apr2013-R Published on 1 April 2013
Name of Tariff: PCCW Home EasyWatch
The Service has ceased to be offered to new customers from 1 April 2013.
Tariff Table
Service Fee including 8 hours storage 498 per month
Installation fee 2,000 per installation
Relocation charge 2,000 per relocation
Video call charge and data access charge apply separately.
"""

HKT_EASYWATCH_COMMERCIAL_TARIFF_2014_TEXT = """
Tariff No.: U0025-014-Jun2014-R Published on 20 June 2014
Name of Tariff: HKT EasyWatch Commercial Service ("Service")
Annex A HKT EasyWatch Commercial Service
The Service includes HKT EasyWatch Plus and PCCW EasyWatch Enterprise Solution.
Rate table for the Service: (All in HK$)
Service Fee 1,500 per month
Installation / Relocation Fee 1,600
Storage Fee 5.00/GB per month (min. 30GB / max. 500GB)
"""

HKT_IP_VOICE_TARIFF_2013_TEXT = """
Tariff No.: U0025-015-May2013-R Published on 31 May 2013
Name of Tariff: Internet Protocol Voice Service (Consumer Customers)
Service fee Unlimited voice calls to any Hong Kong telephone number
except chargeable Infoline service 298/month
Short Message Service 0.5/SMS
Local video call service 1/minute
Installation charge and IDD charges apply separately.
"""

HKT_FREEDOME_NETWORK_SAFETY_TARIFF_2016_TEXT = """
Tariff No.: U0025-019-Dec2016-N Published on 1 December 2016
Name of tariff:
Freedome Network Safety Software ("Freedome")
Description of tariff:
Freedome is an application which aims to offer users private, anonymous and untraceable Internet browsing.
Charges
HK$38 per month per device with a commitment period of 24 months.
Terms and conditions
Freedome is provided only to NETVIGATOR broadband service customers.
Effective date of tariff:
1 December 2016
"""

HKT_NORTON_SECURE_VPN_TARIFF_2020_TEXT = """
Tariff No.: U0025-004-Jun2020-R Published on 1 June 2020
Name of tariff:
Norton Secure VPN ("NSV")
Charges
HK$28 per month per device with a commitment period of 24 months.
Terms and conditions
NSV is provided only to NETVIGATOR broadband service customers.
"""

HKT_EYE2_COMMUNICATION_PACKAGE_TARIFF_2010_TEXT = """
Tariff No.: U025-003 Published on 27 September 2010
Name of Tariff:
eye2 Communication Package
Service Particular of Service Amount of Charges
eye2 Communication Package Note 1
(a) eye2 Telephone Line service Note 2; and
(b) access to various Information Services.
$ 278 or more per month
(It varies depending on subscription of different offers available from Information Service provider(s).)
Short Message Service Local SMS $0.5/SMS
Local video call charges apply separately.
"""

HKT_SEVERE_WEATHER_WARNING_TARIFF_2011_TEXT = """
Tariff No.: U025-020 Published on 24 January 2011
Name of Tariff:
Severe Weather Warning Service ("the Service")
Description of Tariff:
1. For receiving tropical cyclone warning announcement over the phone (minimum period 12 months)
Charges Registration HK$ 300 Service charge HK$ 90 per month
2. For receiving thunderstorm warning announcement over the phone (minimum period 12 months)
Charges Registration HK$ 300 Service charge HK$ 220 per month
3. For receiving flood warning announcement over the phone (minimum period 12 months)
Charges Registration HK$ 300 Service charge HK$ 90 per month
"""

HKT_IDA_SERVICE_TARIFF_2025_TEXT = """
Tariff No.: U0025-001-Jul2025-R Published on 18 July 2025
Name of Tariff: Integrated Digital Access Business Telephone Service ("IDA Service")
Effective date of tariff: 21 July 2025
The charges for IDA Service are set out as below:
Particulars Charge / mth (HK$)
(1) Line Rental
(a) IDA-P Line 20,000
(b) IDA-M Line 20,000
(c) Priority IDA line 20,000
(2) Value-added Services
Block-the-blocker 1,500 / Line
Call forwarding under Smart Biz Line - On-the-go 5,000 / user
"""

HKT_CONSUMER_FIXED_LINE_TARIFF_TEXT = """
Tariff No.: U0025-002-Feb2020-R Published on 10 February 2020
Name of Tariff: Home Phone Service (Consumer Customers)
Rates table:
Particulars Charge (HK$)
(1) Line rental - Leasing of a line/channel enabling one simultaneous call for using a Service 298 / month
(2) VAS To be offered individually or in a package 50 / month per feature
(3) Fixed Line Short Message Service in text format Fixed-to-Fixed HK$0.5/SMS
(4) Other charges Installation charge 680 / line External relocation charge 475 / line
"""

CSL_2G_3G_4G_TARIFF_2014_TEXT = """
Tariff No. U0003-001 Published on 19 September 2014
2G, 3G and 4G Mobile Service
SIM-only Plans HK$600 per month per SIM Mobile data 100MB Local voice 1,000 minutes
Handset/Tablet Plans HK$750 per month per SIM Mobile data 100MB Local voice 1,000 minutes
Thereafter charge HK$40 per 100MB mobile data and HK$1 per minute local voice.
Mobile Service Administration Fee, MTR/Tunnels/Mobile Licence/Administration Fee, IDD deposit and item charges apply separately.
"""

CSL_2G_3G_4G_TARIFF_2012_TEXT = """
Tariff No.: U003-001-May2012-R Published on 3 May 2012
2G, 3G and 4G mobile services
SIM only Plans
3G/4G Service Plans# $199 per month $238 per month
Included Local Data Usage Unlimited Wi-Fi + 5GB+ (original 2.5GB) Unlimited Wi-Fi + 10GB+ (original 5GB)
Included Local Voice Call Minutes 3000 minutes 3000 minutes
2) 3G Multi Smart SIM Plans
3G Multi Smart SIMs Service Plans# $268 per month $328 per month
Included Local Data Usage Unlimited Wi-Fi + 5GB+ (original 2.5GB) Unlimited Wi-Fi + 10GB+ (original 5GB)
3) Handset/Tablet Plans
3G/4G service plan# $389 per month $429 per month
Included Local Data Usage Unlimited Wi-Fi + 5GB+ (original 2.5GB) Unlimited Wi-Fi + 10GB+ (original 5GB)
# Subject to monthly payment of MTR/tunnel/mobile service license and administration charges of $12
"""

CSL_2G_3G_4G_TARIFF_2013_TEXT = """
Tariff No.: U0003-007-Oct2013-R Published on 21 October 2013
2G, 3G and 4G mobile services
1) SIM only Plans
3G/4G Service Plan # $200 per month
Local Data Usage Unlimited Wi-Fi, 1GB
Local Voice Minutes Unlimited
2) Handset/Tablet Plans
3G/4G service plan # $300 per month
Local Data Usage Unlimited Wi-Fi, 1GB
Local Voice Minutes Unlimited
3) Thereafter Charges
Data usage $40 per 200MB per month Voice Minutes $1 per minute
"""

CSL_SMART_PAMA_TARIFF_2017_TEXT = """
Tariff No. U0008-003 Published on 14 March 2017
Postpaid Service Plan
Smart Pama Service Plan
Monthly Fee $298 Monthly Fee Discount $170 Monthly Local Data 6GB
Unlimited monthly local airtime 10,000 local intra-network SMS 200 local MMS
HK$18 Administration Fee applies separately. Local Data Usage after Monthly Local Data is charged at HK$28/200MB or HK$50/GB.
This tariff is available to Hong Kong residents aged 65 or above.
"""

CSL_U_PLAN_TARIFF_2017_TEXT = """
Tariff No. U0008-001 Published on 1 March 2017
Postpaid Service Plan
U-plan
Monthly Fee $298 Monthly Fee Discount $170 Monthly Local Data 6GB
Monthly Local Airtime Unlimited
HK$18 Administration Fee applies separately. Local Data Usage thereafter is charged under the tariff.
This tariff is available to eligible students.
"""

CSL_CLUB_SIM_TARIFF_2017_TEXT = """
Tariff No. U0008-004 Published on 2 August 2017
Postpaid Service Plan
The Club SIM Service Plan
Monthly Fee $28 Monthly Fee Discount $0 Monthly Local Data 1MB
Monthly Local Airtime (thereafter charge) 100 minutes
HK$18 Administration Fee applies separately. Local Data Usage thereafter is charged under the tariff.
"""

CSL_CLUB_SIM_TARIFF_UNTIL_FURTHER_NOTICE_TEXT = """
Tariff No. U0008-005-Sep2017-R Published on 30 September 2017
Postpaid Service Plan
The Club SIM Service Plan
Monthly Fee $28 Monthly Fee Discount $0 Monthly Local Data 1MB
Monthly Local Airtime (thereafter charge) 100 minutes
Revision
Change effect period from Aug 2, 2017- Sep 30, 2017 to Aug 2, 2017 - until further notice.
"""

CSL_CLUB_SIM_TARIFF_CEASED_TEXT = """
Tariff No. U0008-006-Oct2017-R Published on 19 October 2017
Postpaid Service Plan
The Club SIM Service Plan
Monthly Fee $28 Monthly Fee Discount $0 Monthly Local Data 1MB
Monthly Local Airtime (thereafter charge) 100 minutes
This tariff is no longer available for subscription with effect from October 19, 2017.
"""

CSL_1010_POSTPAID_TARIFF_2018_TEXT = """
Tariff No. U0008-002 Published on 22 August 2018
Name of Tariff: Three Postpaid Local Data Service Plans and Greater China Data Service Plans
Three Postpaid Local Data Service Plans
Monthly Fee
5GB $138 Monthly Local Airtime Unlimited
8GB $198 Monthly Local Airtime Unlimited
csl 6GB capacity data package $220 Monthly Local Airtime Unlimited
Greater China Data Service Plans
1O1O 6GB $677 Monthly Local Airtime Unlimited
1O1O 10GB $877 Monthly Local Airtime Unlimited
csl SIM-only Plans 6GB $418 Monthly Local Airtime Unlimited
csl SIM-only Plans 10GB $618 Monthly Local Airtime Unlimited
csl Handset/Tablet Plans 6GB $618 Monthly Local Airtime Unlimited
csl Handset/Tablet Plans 10GB $818 Monthly Local Airtime Unlimited
Monthly fee discounts, MTR/tunnel/mobile licence/administration fees and usage thereafter charges apply separately.
"""

HKT_SME_5G_BUSINESS_TEXT = """
5G Business Mobile Sim Plan
5G Basic Plan Unlimited Data Usage Plan Unlimited local 5G data
（30GB + 1 Mbps unlimited thereafter） Unlimited local voice call minutes
Free 3GB/month data roaming in Mainland China & Macau Waived $18/month tunnel fee
Starting from 128/month Enquire Now
Chinese Mainland Roaming Data Plan 【Limited】4-day Asia Pacific Data Roaming Pass
25GB Chinese Mainland Roaming data Unlimited local voice call minutes 30GB local 5G data
Waived $18/month tunnel fee Starting from $199/month Enquire Now
Samsung Smartphones Subscription Plan Samsung Galaxy A17 (6+128GB)(Value: $1,598)
Unlimited local 5G data （1GB + 128 Kbps unlimited thereafter） 2,000mins local voice call
Waived $18/month tunnel fee Starting from $104/month Enquire Now
"""

HKT_SME_BUSINESS_BROADBAND_TEXT = """
Business Broadband
Ultra-fast Business Broadband 5G Business Broadband
Ultra-fast Business Broadband A reliable network for your business
Starting from HK$198 / Month
Fast, Stable and Secured With Fiber-to-the-Office (FTTO) technology and an unrivaled number of exchange buildings,
HKT provides SMEs with an optimally smooth and stable network ranging from 300M to 100G.
Learn More
5G Business Broadband Flexible to meet your business needs
Starting from HK$198 / Month
99.9% Business District Network Coverage
No Cabling Needed
Fixed IP and cybersecurity services are provided for your business needs.
Macbook for SMEs
Terms & Condition This service is for commercial customers only, not for personal or residential users.
"""

TEN_TEN_INFINITE_ENTERTAINMENT_TEXT = """
Infinite Entertainment 5G Prestige Service (sports pack) HK$ 509 .00 / month
Commitment period: 24 / 36 months Unlimited 5G data
Monthly roaming mobile data usage : 3GB Local voice call minutes : Unlimited
Included Now TV packs : Super Sports Pack Plus & Asia Signature Pack
Infinite Entertainment 5G Prestige Service (entertainment pack) HK$ 559 .00 / month
Commitment period: 24 / 36 months Unlimited 5G data
Monthly roaming mobile data usage : 3GB Local voice call minutes : Unlimited
Included Now TV packs : Asia Signature Pack, Western Signature Pack, Disney+ Standard
Also payable is an Administration Fee of HK$18 per month.
Customers who subscribe to the monthly fee service plan of HK$509/$559 can enjoy
1TB of local mobile data usage per month for the first 6 months, followed by
500GB of local mobile data usage per month thereafter.
"""

CSL_OLD_HORIZONTAL_TEXT = """
Data and Voice Service Plan
Monthly SIM –only plan fee HK$158 HK$198 HK$298 HK$438
Monthly handset plan fee HK$298 HK$408 HK$548 HK$738
Local data usage + data bonus 5GB 6GB+2GB 6GB+6GB 10GB+10GB
China roaming data service Additional charges apply
Voice call mins Unlimited
"""

CSL_OLD_VERTICAL_TEXT = """
Data and Voice Service Plan
Monthly SIM only plan fee $158
Monthly handset plan fee $298
Local data usage 5GB
Voice call mins Unlimited
Monthly SIM only plan fee $198
Monthly handset plan fee $408
Local data usage 6GB+2GB
Voice call mins Unlimited
Monthly SIM only plan fee $298
Monthly handset plan fee $548
Local data usage 6GB+2GB
Voice call mins Unlimited
Mainland China & Macau roaming data usage 2GB
Other services
"""

CSL_ULTRA_OLD_TEXT = """
csl Ultra 450* Service Plan
Handset Plan Monthly Fee (1) (3) $298 $408 $498 $638
SIM Only Plan Monthly Fee (2) (3) $198 $238 $298 $438
Local Data usage (6) (8) (11) 1GB 2.5GB 6GB 10GB
Top-up Data Package $28 / 200MB or $50 / GB
Piggy Bank Data Carry Forward Service (28) $48 per month
You are required to pay a MTR/Tunnels/Mobile License/Administration Fee of $18 per month.
The Service Charge for DataRoam Day Pass is HK$198 per SIM Card, per day.
"""

HKT_ENTERPRISE_LOCAL_BUSINESS_TELEPHONE_TEXT = """
Local Business Telephone Services
Standard Charge: Installation Charge $600 Monthly Charge $189.80
Other Service Charges: Change of telephone number $200 Change of address relocation External removal $300
Tone DDI line Installation $600/line Monthly Charge $281/line
DDI Diversity (with Adjacent Exchange Diversity) $379/line
Pulse DDI line Installation $600/line Monthly Charge $344/line
DDI Diversity (with Adjacent Exchange Diversity) $442/line
Business Telephone line Monthly Charge $189.80/line Business Select line Monthly Charge $237/line
Datel Monthly Charge: $198.80 (including telephone line charge)
IDA (T1) Installation $3,600/line Monthly rental $3,950/line
Hunting Line Monthly Charge $209 Premium Hunting Monthly Charge $237
Basic Fax - Installation $600/line - Monthly Charge $198.8/line
Faxline 100 - Installation $600/line - Monthly Charge $229.8/line
Faxline 3 - Installation $600/line - Monthly Charge $237.8/line
Faxline 100 - Hunting - Installation $600/line - Monthly Charge $249/line
Citinet - Installation charge $600 - Monthly Charge $213
Caller Display phone monthly charge - PANASONIC KX-TSC11MXW $35/unit
Caller Display + PhoneMail for only $48/month
"""

HKT_ENTERPRISE_LOCAL_BUSINESS_TELEPHONE_TC_TEXT = """
本地電話服務
標準價目： 安裝費 $600 月費 $189.80
其他服務費用： 更改電話號碼 $200 更改安裝地址 $300
音頻直通內線 - 安裝費 $600（每條） - 月費 $281（每條）
直通內線分途（與附近機樓分途） $379（每條）
脈衝直通內線 - 安裝費 $600（每條） - 月費 $344（每條）
直通內線分途（與附近機樓分途） $442（每條）
商業電話線 - 月費 $189.80（每條） 商業智選 - 月費 $237（每條）
價目：月費（包括租用電話線）$198.80
IDA (T1) - 安裝費 $3,600（每條） - 月費 $3,950（每條）
安裝費 $600 自動跳駁線月費 $209 商務通1月費 $237
商用傳真 - 安裝費 $600（每條） - 月費 $198.8（每條）
商用傳真100 - 安裝費 $600（每條） - 月費 $229.8（每條）
商用傳真3 - 安裝費 $600（每條） - 月費 $237.8（每條）
Faxline 100 - Hunting - 安裝費 $600（每條） - 月費 $249（每條）
城訊通 - 安裝費 $600 - 月費 $213
來電顯示電話月租 - PANASONIC KX-TSC11MXW電話 $35（每部）
每月僅需$48
"""

HKT_HOMEPHONE_VALUE_ADDED_SERVICES_TEXT = """
HKT Home Phone Service provides a diversity of value-added services such as Call Forwarding, Caller Display and Block-the-Blocker.
Calling Features Service Fee per Month #
Deluxe Package (Caller Display, Call Waiting, Conference Calling and other 6 features) Comprises nine of the most popular features to help you manage your calls efficiently. HK$27
Abbreviated Dialing Make a call by dialing just two digits. HK$16
Appointment Service This service performs like a sophisticated alarm clock. HK$16
Block-the-Blocker rejects anonymous callers. HK$8
Call Forwarding You can forward all incoming calls to any local telephone number. HK$20
Conference Calling You can conduct three-way conference calls. HK$17
Music on Hold The caller will hear a soft melody when placed on hold. HK$3
OneCall This provides you with a virtual number. HK$38 (new subscribers must sign up to a service plan with commitment period)
PhoneMail is a computerized message-taking service. HK$25
Home Junk Call Blocking Free
Smart Care Voice Reminder Service After setting reminders, your home phone will receive a call. $48
# These fees are charged in addition to your standard monthly service fee for your HKT Telephone Line Service, and are subject to change from time to time.
"""

HKT_LOCAL_BUSINESS_TELEPHONE_TARIFF_PDF_TEXT = """
Name of Tariff: Local Business Telephone Service
The charges for the Service are set out as below:
Particulars Charge / mth (HK$)
(1) Line Rental
(a) Business Telephone Line and Business Select Series 300 / line
(b) Business Faxline and Datel Series 300 / line
(c) Business Hunting Line Series 300 / line
(d) Business Citinet Line Series 550 / line
(e) Direct-Dialing-In ("DDI") Line Series6 550 / line
(f) Next Generation Business Fixed Line ("NGBFL") Series7 300 / line
(2) Value-added Services ("VAS")
(a) Abbreviated dialing 40
Installation, relocation and reconnection charges are set out separately.
"""


class HktProductCrawlTest(unittest.TestCase):
    def test_extracts_current_csl_and_1010_plans(self) -> None:
        def fake_fetcher(_client, url):
            if "hkcsl" in url:
                text = CSL_TEXT
            elif "1010" in url:
                text = TEN_TEN_TEXT
            elif "list-price" in url:
                text = NETVIGATOR_LIST_PRICE_TEXT
            elif "netvigator" in url:
                text = NETVIGATOR_INDEX_TEXT
            else:
                text = "HKT Enterprise 5G business mobile product page"
            return {
                "url": url,
                "final_url": url,
                "status": 200,
                "content_type": "text/html",
                "bytes": len(text),
                "title": "",
                "text": text,
                "error": "",
                "method": "fake",
            }

        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            status = crawl_hkt_products(fetcher=fake_fetcher, output_dir=output_dir, include_historical=False)
            with (output_dir / "latest_products.csv").open(encoding="utf-8-sig") as fh:
                rows = list(csv.DictReader(fh))

        by_fee = {(row["brand"], row["monthly_fee_hkd"]): row for row in rows}
        self.assertTrue(status["ok"])
        self.assertEqual(by_fee[("csl", "348")]["local_data_gb"], "100")
        self.assertEqual(by_fee[("csl", "348")]["roaming_data_gb"], "3")
        self.assertEqual(by_fee[("1O1O", "459")]["local_data_gb"], "150")
        self.assertEqual(by_fee[("1O1O", "459")]["roaming_data_gb"], "3")
        self.assertEqual(by_fee[("1O1O", "299")]["local_data_gb"], "30")
        self.assertEqual(by_fee[("1O1O", "299")]["roaming_data_gb"], "1")
        self.assertEqual(by_fee[("NETVIGATOR", "108")]["contract_months"], "36")
        self.assertEqual(by_fee[("NETVIGATOR", "698")]["post_fup_speed_mbps"], "1000")
        self.assertEqual(by_fee[("NETVIGATOR", "8888")]["post_fup_speed_mbps"], "50000")

    def test_extracts_old_netvigator_list_price_variants(self) -> None:
        source = {
            "source_id": "netvigator_list_price_20190825",
            "brand": "NETVIGATOR",
            "product_category": "home_fibre_broadband",
            "url": "https://www.netvigator.com/eng/info/list-price.html",
            "official_source_type": "wayback_official_page_snapshot",
        }
        result = {
            "url": source["url"],
            "final_url": source["url"],
            "status": 200,
            "content_type": "text/html",
            "bytes": len(NETVIGATOR_OLD_LIST_PRICE_TEXT),
            "title": "",
            "text": NETVIGATOR_OLD_LIST_PRICE_TEXT,
            "error": "",
            "method": "fake",
        }
        rows = _parse_netvigator_list_price(source, result, "2026-07-06T00:00:00+08:00")
        by_fee = {row["monthly_fee_hkd"]: row for row in rows}

        self.assertEqual(len(rows), 5)
        self.assertEqual(by_fee["2888"]["post_fup_speed_mbps"], "10000")
        self.assertEqual(by_fee["998"]["plan_name"], "NETVIGATOR list price 4x1000M Multi-Use Broadband Service")
        self.assertEqual(by_fee["598"]["contract_months"], "24")

    def test_extracts_csl_netvigator_5g_home_internet_offers(self) -> None:
        source = {
            "source_id": "netvigator_csl_5g_home_internet_offer",
            "brand": "NETVIGATOR",
            "product_category": "home_5g_broadband",
            "url": "https://www.netvigator.com/chi/promotion/5G-Home-Internet.html",
            "official_source_type": "official_public_product_page",
        }
        result = {
            "url": source["url"],
            "final_url": source["url"],
            "status": 200,
            "content_type": "text/html",
            "bytes": len(NETVIGATOR_CSL_5G_HOME_INTERNET_TEXT),
            "title": "",
            "text": NETVIGATOR_CSL_5G_HOME_INTERNET_TEXT,
            "error": "",
            "method": "fake",
        }
        rows = _parse_netvigator_csl_5g_home_internet(source, result, "2026-07-10T00:00:00+08:00")
        self.assertEqual([(row["monthly_fee_hkd"], row["local_data_gb"]) for row in rows], [("168", "250"), ("198", "250")])
        self.assertTrue(all(row["add_on_charges_hkd"] == "HK$18 monthly administration fee waived during the designated commitment period." for row in rows))

    def test_extracts_hkt_official_internet_access_tariff_pdf_rows(self) -> None:
        source = {
            "source_id": "hkt_internet_access_tariff_20260106",
            "brand": "NETVIGATOR",
            "product_category": "official_tariff_internet_access",
            "url": "https://www.hkt.com/api-service/assets/U0025-001-Jan2026-R_Internet_Access_Services.pdf",
            "official_source_type": "official_public_tariff_pdf",
            "published_on": "2026-01-06",
        }
        result = {
            "url": source["url"],
            "final_url": source["url"],
            "status": 200,
            "content_type": "application/pdf",
            "bytes": len(HKT_INTERNET_ACCESS_TARIFF_2026_TEXT),
            "title": "PDF",
            "text": HKT_INTERNET_ACCESS_TARIFF_2026_TEXT,
            "error": "",
            "method": "fake_pdf",
        }
        rows = _parse_hkt_internet_access_tariff_pdf(source, result, "2026-07-06T00:00:00+08:00")
        by_fee = {row["monthly_fee_hkd"]: row for row in rows}

        self.assertEqual(len(rows), 4)
        self.assertEqual(by_fee["700"]["extraction_status"], "parsed_official_tariff_pdf")
        self.assertEqual(by_fee["3500"]["post_fup_speed_mbps"], "4000")
        self.assertEqual(by_fee["8888"]["post_fup_speed_mbps"], "50000")
        self.assertIn("not a promotional retail offer", by_fee["8888"]["add_on_charges_hkd"])

    def test_extracts_hkt_official_2015_internet_access_tariff_pdf_rows(self) -> None:
        source = {
            "source_id": "hkt_internet_access_tariff_20150210",
            "brand": "NETVIGATOR",
            "product_category": "official_tariff_internet_access",
            "url": "https://www.hkt.com/api-service/assets/U0025-003-Feb2015-R%20Internet%20Acces.pdf",
            "official_source_type": "official_public_tariff_pdf",
            "published_on": "2015-02-10",
        }
        result = {
            "url": source["url"],
            "final_url": source["url"],
            "status": 200,
            "content_type": "application/pdf",
            "bytes": len(HKT_INTERNET_ACCESS_TARIFF_2015_TEXT),
            "title": "PDF",
            "text": HKT_INTERNET_ACCESS_TARIFF_2015_TEXT,
            "error": "",
            "method": "fake_pdf",
        }
        rows = _parse_hkt_internet_access_tariff_pdf(source, result, "2026-07-08T00:00:00+08:00")
        by_fee = {row["monthly_fee_hkd"]: row for row in rows}

        self.assertEqual(len(rows), 2)
        self.assertEqual(by_fee["3500"]["post_fup_speed_mbps"], "10000")
        self.assertEqual(by_fee["700"]["post_fup_speed_mbps"], "100")
        self.assertIn("2015-02-10", by_fee["3500"]["plan_name"])

    def test_extracts_hkt_official_business_broadband_tariff_pdf_rows(self) -> None:
        source = {
            "source_id": "hkt_business_broadband_tariff_20160229",
            "brand": "HKT Enterprise",
            "product_category": "official_tariff_business_broadband",
            "url": "https://www.hkt.com/api-service/assets/U0025-006-Feb2016-R%20Business%20Broad.pdf",
            "official_source_type": "official_public_tariff_pdf",
            "published_on": "2016-02-29",
        }
        result = {
            "url": source["url"],
            "final_url": source["url"],
            "status": 200,
            "content_type": "application/pdf",
            "bytes": len(HKT_BUSINESS_BROADBAND_TARIFF_2016_TEXT),
            "title": "PDF",
            "text": HKT_BUSINESS_BROADBAND_TARIFF_2016_TEXT,
            "error": "",
            "method": "fake_pdf",
        }
        rows = _parse_hkt_business_broadband_tariff_pdf(source, result, "2026-07-06T00:00:00+08:00")
        by_fee = {row["monthly_fee_hkd"]: row for row in rows}

        self.assertEqual(len(rows), 10)
        self.assertEqual(by_fee["2500"]["post_fup_speed_mbps"], "100")
        self.assertIn("Business Broadband tariff 2016-02-29", by_fee["3000"]["plan_name"])
        self.assertEqual(by_fee["1500000"]["plan_name"], "HKT Enterprise official Business Broadband tariff 2016-02-29 - Metro-Internet")
        self.assertIn("not promotional retail offer", by_fee["1500000"]["add_on_charges_hkd"])

    def test_extracts_hkt_official_premium_broadband_tariff_pdf_rows(self) -> None:
        source = {
            "source_id": "hkt_premium_broadband_tariff_20161130",
            "brand": "HKT Enterprise",
            "product_category": "official_tariff_premium_broadband",
            "url": "https://www.hkt.com/api-service/assets/U0025-017-Nov2016-R%20Premium%20Broadb.pdf",
            "official_source_type": "official_public_tariff_pdf",
            "published_on": "2016-11-30",
            "effective_from": "2017-01-10",
        }
        result = {
            "url": source["url"],
            "final_url": source["url"],
            "status": 200,
            "content_type": "application/pdf",
            "bytes": len(HKT_PREMIUM_BROADBAND_TARIFF_2016_TEXT),
            "title": "PDF",
            "text": HKT_PREMIUM_BROADBAND_TARIFF_2016_TEXT,
            "error": "",
            "method": "fake_pdf",
        }
        rows = _parse_hkt_premium_broadband_tariff_pdf(source, result, "2026-07-06T00:00:00+08:00")
        by_fee = {row["monthly_fee_hkd"]: row for row in rows}

        self.assertEqual(len(rows), 15)
        self.assertEqual(by_fee["420"]["post_fup_speed_mbps"], "8")
        self.assertEqual(by_fee["120060"]["post_fup_speed_mbps"], "1000")
        self.assertIn("effective 2017-01-10", by_fee["2760"]["plan_name"])
        self.assertIn("installation/deletion/change charges excluded", by_fee["2760"]["add_on_charges_hkd"])
        self.assertIn("not promotional retail offer", by_fee["27600"]["add_on_charges_hkd"])

    def test_extracts_hkt_official_metro_ip_service_tariff_pdf_rows(self) -> None:
        source = {
            "source_id": "hkt_metro_ip_service_tariff_20191115",
            "brand": "HKT Enterprise",
            "product_category": "official_tariff_metro_ip",
            "url": "https://www.hkt.com/api-service/assets/U0025-005-Nov2019-R%20Metro%20IP%20Servi.pdf",
            "official_source_type": "official_public_tariff_pdf",
            "published_on": "2019-11-15",
        }
        result = {
            "url": source["url"],
            "final_url": source["url"],
            "status": 200,
            "content_type": "application/pdf",
            "bytes": len(HKT_METRO_IP_SERVICE_TARIFF_2019_TEXT),
            "title": "PDF",
            "text": HKT_METRO_IP_SERVICE_TARIFF_2019_TEXT,
            "error": "",
            "method": "fake_pdf",
        }
        rows = _parse_hkt_metro_ip_service_tariff_pdf(source, result, "2026-07-08T00:00:00+08:00")
        by_plan = {row["plan_name"]: row for row in rows}

        self.assertEqual(len(rows), 7)
        self.assertEqual(by_plan["HKT Enterprise official Metro IP Service Silver Plan 512K~10Mbps tariff 2019-11-15"]["monthly_fee_hkd"], "20000")
        self.assertEqual(by_plan["HKT Enterprise official Metro IP Service Gold Plan 901~1000 tariff 2019-11-15"]["post_fup_speed_mbps"], "1000")
        self.assertEqual(by_plan["HKT Enterprise official Metro IP Service Diamond Plan 1~10 tariff 2019-11-15"]["contract_months"], "12")
        self.assertIn("setup, internal/external relocation and reconfiguration charges", rows[0]["add_on_charges_hkd"])

    def test_extracts_hkt_official_flexible_bandwidth_tariff_pdf_rows(self) -> None:
        source = {
            "source_id": "hkt_flexible_bandwidth_service_tariff_20190131",
            "brand": "HKT Enterprise",
            "product_category": "official_tariff_flexible_bandwidth",
            "url": "https://www.hkt.com/api-service/assets/U0025-001-Jan2019-R%20Flexible%20Bandw.pdf",
            "official_source_type": "official_public_tariff_pdf",
            "published_on": "2019-01-31",
        }
        result = {
            "url": source["url"],
            "final_url": source["url"],
            "status": 200,
            "content_type": "application/pdf",
            "bytes": len(HKT_FLEXIBLE_BANDWIDTH_TARIFF_2019_TEXT),
            "title": "PDF",
            "text": HKT_FLEXIBLE_BANDWIDTH_TARIFF_2019_TEXT,
            "error": "",
            "method": "fake_pdf",
        }
        rows = _parse_hkt_flexible_bandwidth_service_tariff_pdf(source, result, "2026-07-09T00:00:00+08:00")
        by_plan = {row["plan_name"]: row for row in rows}

        self.assertEqual(len(rows), 11)
        self.assertEqual(by_plan["HKT Enterprise official Flexible Bandwidth Service Point-to-Multipoint Server End 1-50 Mbps tariff 2019-01-31"]["monthly_fee_hkd"], "15000")
        self.assertEqual(by_plan["HKT Enterprise official Flexible Bandwidth Service Point-to-Multipoint Client End GE interface 501-1000 Mbps tariff 2019-01-31"]["post_fup_speed_mbps"], "1000")
        self.assertEqual(by_plan["HKT Enterprise official Flexible Bandwidth Service Point-to-Point Service 100 Gbps tariff 2019-01-31"]["monthly_fee_hkd"], "1500000")
        self.assertNotIn("7400", {row["monthly_fee_hkd"] for row in rows})
        self.assertIn("one-off installation, relocation, reconfiguration, diversity option", rows[0]["add_on_charges_hkd"])

    def test_extracts_hkt_official_megalink_tariff_pdf_rows(self) -> None:
        source = {
            "source_id": "hkt_megalink_service_tariff_20131209",
            "brand": "HKT Enterprise",
            "product_category": "official_tariff_megalink",
            "url": "https://www.hkt.com/api-service/assets/U0025-034-Dec2013-R%20Megalink%20Servi.pdf",
            "official_source_type": "official_public_tariff_pdf",
            "published_on": "2013-12-09",
            "effective_from": "2014-01-10",
        }
        result = {
            "url": source["url"],
            "final_url": source["url"],
            "status": 200,
            "content_type": "application/pdf",
            "bytes": len(HKT_MEGALINK_TARIFF_2013_TEXT),
            "title": "PDF",
            "text": HKT_MEGALINK_TARIFF_2013_TEXT,
            "error": "",
            "method": "fake_pdf",
        }
        rows = _parse_hkt_megalink_service_tariff_pdf(source, result, "2026-07-09T00:00:00+08:00")
        by_plan = {row["plan_name"]: row for row in rows}

        self.assertEqual(len(rows), 32)
        self.assertEqual(
            by_plan["HKT Enterprise official MegaLink Service effective 2014-01-10 - MegaLink Access Client End - Asymmetric 10Base-T bridging or ATM-25 8M"]["monthly_fee_hkd"],
            "459",
        )
        self.assertEqual(
            by_plan["HKT Enterprise official MegaLink Service effective 2014-01-10 - MegaLink Access Server End - OC-3c or FE first 15 km up to 100M"]["monthly_fee_hkd"],
            "57820",
        )
        self.assertEqual(
            by_plan["HKT Enterprise official MegaLink Service effective 2014-01-10 - MegaLink VPN Server End - Symmetric GE bandwidth per 50M 50M bandwidth block"]["post_fup_speed_mbps"],
            "50",
        )
        self.assertEqual(rows[0]["contract_months"], "12")
        self.assertNotIn("690", {row["monthly_fee_hkd"] for row in rows})
        self.assertIn("installation, internal/external relocation, reconfiguration", rows[0]["add_on_charges_hkd"])

    def test_extracts_hkt_official_megalink_2012_tariff_pdf_rows(self) -> None:
        source = {
            "source_id": "hkt_megalink_service_tariff_20120703",
            "brand": "HKT Enterprise",
            "product_category": "official_tariff_megalink",
            "url": "https://www.hkt.com/api-service/assets/U025-006-Jul2012-R%20Megalink%20Servic.pdf",
            "official_source_type": "official_public_tariff_pdf",
            "published_on": "2012-07-03",
            "effective_from": "2012-07-03",
        }
        result = {
            "url": source["url"],
            "final_url": source["url"],
            "status": 200,
            "content_type": "application/pdf",
            "bytes": len(HKT_MEGALINK_TARIFF_2012_TEXT),
            "title": "PDF",
            "text": HKT_MEGALINK_TARIFF_2012_TEXT,
            "error": "",
            "method": "fake_pdf",
        }
        rows = _parse_hkt_megalink_service_tariff_pdf(source, result, "2026-07-09T00:00:00+08:00")
        by_plan = {row["plan_name"]: row for row in rows}

        self.assertEqual(len(rows), 32)
        self.assertEqual(
            by_plan["HKT Enterprise official MegaLink Service effective 2012-07-03 - MegaLink Access Client End - Asymmetric 10Base-T bridging or ATM-25 8M"]["monthly_fee_hkd"],
            "399",
        )
        self.assertEqual(
            by_plan["HKT Enterprise official MegaLink Service effective 2012-07-03 - MegaLink VPN Client End - Asymmetric G.DMT 6M"]["monthly_fee_hkd"],
            "2235",
        )
        self.assertEqual(
            by_plan["HKT Enterprise official MegaLink Service effective 2012-07-03 - MegaLink VPN Server End - Symmetric GE bandwidth per 50M 50M bandwidth block"]["monthly_fee_hkd"],
            "5650",
        )

    def test_extracts_hkt_official_megalink_2016_revision_tariff_pdf_rows(self) -> None:
        source = {
            "source_id": "hkt_megalink_service_tariff_20161130",
            "brand": "HKT Enterprise",
            "product_category": "official_tariff_megalink",
            "url": "https://www.hkt.com/api-service/assets/U0025-016-Nov2016-R%20Megalink%20Servi.pdf",
            "official_source_type": "official_public_tariff_pdf",
            "published_on": "2016-11-30",
            "effective_from": "2017-01-10",
        }
        result = {
            "url": source["url"],
            "final_url": source["url"],
            "status": 200,
            "content_type": "application/pdf",
            "bytes": len(HKT_MEGALINK_TARIFF_2016_TEXT),
            "title": "PDF",
            "text": HKT_MEGALINK_TARIFF_2016_TEXT,
            "error": "",
            "method": "fake_pdf",
        }
        rows = _parse_hkt_megalink_service_tariff_pdf(source, result, "2026-07-09T00:00:00+08:00")
        by_plan = {row["plan_name"]: row for row in rows}

        self.assertEqual(len(rows), 32)
        self.assertEqual(
            by_plan["HKT Enterprise official MegaLink Service effective 2017-01-10 - MegaLink Access Client End - Asymmetric 10Base-T bridging or ATM-25 8M"]["monthly_fee_hkd"],
            "560",
        )
        self.assertEqual(
            by_plan["HKT Enterprise official MegaLink Service effective 2017-01-10 - MegaLink Access Server End - OC-3c or FE first 15 km up to 100M"]["monthly_fee_hkd"],
            "69390",
        )
        self.assertEqual(
            by_plan["HKT Enterprise official MegaLink Service effective 2017-01-10 - MegaLink VPN Server End - Symmetric GE bandwidth per 50M 50M bandwidth block"]["monthly_fee_hkd"],
            "7800",
        )
        self.assertNotIn("830", {row["monthly_fee_hkd"] for row in rows})

    def test_extracts_hkt_official_megalink_2023_revision_tariff_pdf_rows(self) -> None:
        source = {
            "source_id": "hkt_megalink_service_tariff_20230919",
            "brand": "HKT Enterprise",
            "product_category": "official_tariff_megalink",
            "url": "https://www.hkt.com/api-service/assets/U0025-005-Sep2023-R%20Megalink%20Servi.pdf",
            "official_source_type": "official_public_tariff_pdf",
            "published_on": "2023-09-19",
            "effective_from": "2023-09-19",
        }
        result = {
            "url": source["url"],
            "final_url": source["url"],
            "status": 200,
            "content_type": "application/pdf",
            "bytes": len(HKT_MEGALINK_TARIFF_2023_TEXT),
            "title": "PDF",
            "text": HKT_MEGALINK_TARIFF_2023_TEXT,
            "error": "",
            "method": "fake_pdf",
        }
        rows = _parse_hkt_megalink_service_tariff_pdf(source, result, "2026-07-09T00:00:00+08:00")
        by_plan = {row["plan_name"]: row for row in rows}

        self.assertEqual(len(rows), 26)
        self.assertEqual(
            by_plan["HKT Enterprise official MegaLink Service effective 2023-09-19 - MegaLink VPN Client End - Asymmetric 10Base-T or ATM-25 up to 6M flat monthly rental"]["monthly_fee_hkd"],
            "20000",
        )
        self.assertEqual(
            by_plan["HKT Enterprise official MegaLink Service effective 2023-09-19 - MegaLink VPN Client End - Symmetric 10/100Base-T 25M"]["monthly_fee_hkd"],
            "50000",
        )
        self.assertNotIn(
            "HKT Enterprise official MegaLink Service effective 2023-09-19 - MegaLink VPN Client End - Asymmetric G.DMT 1.5M",
            by_plan,
        )

    def test_extracts_hkt_official_datapak_2013_tariff_pdf_rows(self) -> None:
        source = {
            "source_id": "hkt_datapak_private_circuit_tariff_20131105",
            "brand": "HKT Enterprise",
            "product_category": "official_tariff_datapak_private_circuit",
            "url": "https://www.hkt.com/api-service/assets/U0025-031-Nov2013-R%20Datapak%20Servic.pdf",
            "official_source_type": "official_public_tariff_pdf",
            "published_on": "2013-11-05",
        }
        result = {
            "url": source["url"],
            "final_url": source["url"],
            "status": 200,
            "content_type": "application/pdf",
            "bytes": len(HKT_DATAPAK_TARIFF_2013_TEXT),
            "title": "PDF",
            "text": HKT_DATAPAK_TARIFF_2013_TEXT,
            "error": "",
            "method": "fake_pdf",
        }
        rows = _parse_hkt_datapak_private_circuit_tariff_pdf(source, result, "2026-07-09T00:00:00+08:00")
        by_plan = {row["plan_name"]: row for row in rows}

        self.assertEqual(len(rows), 24)
        self.assertEqual(by_plan["HKT Enterprise official Datapak/Private Circuit tariff 2013-11-05 - Datapak Fiberline Service - 10 Gigabit Ethernet"]["monthly_fee_hkd"], "140000")
        self.assertEqual(by_plan["HKT Enterprise official Datapak/Private Circuit tariff 2013-11-05 - Datapak Fiberline DWDM - 4 interfaces and bandwidth of 2.5G"]["post_fup_speed_mbps"], "2500")
        self.assertEqual(by_plan["HKT Enterprise official Datapak/Private Circuit tariff 2013-11-05 - Internal Leased Circuit - private circuit within same building 2-wire"]["monthly_fee_hkd"], "117.8")
        self.assertNotIn("56610", {row["monthly_fee_hkd"] for row in rows})

    def test_extracts_hkt_official_datapak_2023_tariff_pdf_rows(self) -> None:
        source = {
            "source_id": "hkt_datapak_private_circuit_tariff_20230915",
            "brand": "HKT Enterprise",
            "product_category": "official_tariff_datapak_private_circuit",
            "url": "https://www.hkt.com/api-service/assets/U0025-004-Sep2023-R%20Datapak%20Servic.pdf",
            "official_source_type": "official_public_tariff_pdf",
            "published_on": "2023-09-15",
        }
        result = {
            "url": source["url"],
            "final_url": source["url"],
            "status": 200,
            "content_type": "application/pdf",
            "bytes": len(HKT_DATAPAK_TARIFF_2023_TEXT),
            "title": "PDF",
            "text": HKT_DATAPAK_TARIFF_2023_TEXT,
            "error": "",
            "method": "fake_pdf",
        }
        rows = _parse_hkt_datapak_private_circuit_tariff_pdf(source, result, "2026-07-09T00:00:00+08:00")
        by_plan = {row["plan_name"]: row for row in rows}

        self.assertEqual(len(rows), 28)
        self.assertEqual(by_plan["HKT Enterprise official Datapak/Private Circuit tariff 2023-09-15 - Datapak Fiberline Service - Gigabit Ethernet 200M"]["monthly_fee_hkd"], "28200")
        self.assertEqual(by_plan["HKT Enterprise official Datapak/Private Circuit tariff 2023-09-15 - Datapak Fiberline Service - STM1/OC3"]["monthly_fee_hkd"], "70000")
        self.assertEqual(by_plan["HKT Enterprise official Datapak/Private Circuit tariff 2023-09-15 - Internal Leased Circuit - private circuit within same building 4-wire"]["monthly_fee_hkd"], "446")
        self.assertNotIn("18600", {row["monthly_fee_hkd"] for row in rows})

    def test_registers_verified_hkt_datapak_historical_revision_nodes(self) -> None:
        source_ids = {source["snapshot_id"] for source in OFFICIAL_TARIFF_DOCUMENT_SOURCES}
        self.assertTrue(
            {
                "hkt_datapak_private_circuit_tariff_20120903",
                "hkt_datapak_private_circuit_tariff_20121012",
                "hkt_datapak_private_circuit_tariff_20140626",
                "hkt_datapak_private_circuit_tariff_20150926",
                "hkt_datapak_private_circuit_tariff_20151027",
                "hkt_datapak_private_circuit_tariff_20161130",
                "hkt_datapak_private_circuit_tariff_20180401",
                "hkt_datapak_private_circuit_tariff_20221116",
                "hkt_datapak_private_circuit_tariff_20230401",
            }.issubset(source_ids)
        )

    def test_extracts_hkt_official_one_communications_tariff_pdf_rows(self) -> None:
        source = {
            "source_id": "hkt_one_communications_tariff_20110708",
            "brand": "HKT Enterprise",
            "product_category": "official_tariff_one_communications",
            "url": "https://www.hkt.com/api-service/assets/U025-031_one_communications.pdf",
            "official_source_type": "official_public_tariff_pdf",
            "published_on": "2011-07-08",
        }
        result = {
            "url": source["url"],
            "final_url": source["url"],
            "status": 200,
            "content_type": "application/pdf",
            "bytes": len(HKT_ONE_COMMUNICATIONS_TARIFF_2011_TEXT),
            "title": "PDF",
            "text": HKT_ONE_COMMUNICATIONS_TARIFF_2011_TEXT,
            "error": "",
            "method": "fake_pdf",
        }
        rows = _parse_hkt_one_communications_tariff_pdf(source, result, "2026-07-07T00:00:00+08:00")
        by_fee = {row["monthly_fee_hkd"]: row for row in rows}

        self.assertEqual(len(rows), 13)
        self.assertIn("Plan A Staff", by_fee["258"]["plan_name"])
        self.assertIn("Plan M Enterprise Centrex Operator", by_fee["548"]["plan_name"])
        self.assertIn("FMC features HK$98/user/month", by_fee["208"]["add_on_charges_hkd"])
        self.assertIn("voice service only", by_fee["238"]["local_voice"])

    def test_extracts_hkt_official_telecommunications_backup_tariff_pdf_rows(self) -> None:
        source = {
            "source_id": "hkt_telecommunications_backup_tariff_20130601",
            "brand": "HKT Enterprise",
            "product_category": "official_tariff_telecommunications_backup",
            "url": "https://www.hkt.com/api-service/assets/U0025-024-Jun2013-RTelecommunicati.pdf",
            "official_source_type": "official_public_tariff_pdf",
            "published_on": "2013-06-01",
        }
        result = {
            "url": source["url"],
            "final_url": source["url"],
            "status": 200,
            "content_type": "application/pdf",
            "bytes": len(HKT_TELECOMMUNICATIONS_BACKUP_TARIFF_2013_TEXT),
            "title": "PDF",
            "text": HKT_TELECOMMUNICATIONS_BACKUP_TARIFF_2013_TEXT,
            "error": "",
            "method": "fake_pdf",
        }
        rows = _parse_hkt_telecommunications_backup_tariff_pdf(source, result, "2026-07-08T00:00:00+08:00")
        by_name = {row["plan_name"]: row for row in rows}

        self.assertEqual(len(rows), 9)
        self.assertEqual(by_name["HKT Enterprise official Telecommunications Backup Service - Continuity Plan CPC 1-50 Lines tariff 2013-06-01"]["monthly_fee_hkd"], "2500")
        self.assertEqual(by_name["HKT Enterprise official Telecommunications Backup Service - IDA-P Mutual Backup Service per IDA-P Line tariff 2013-06-01"]["monthly_fee_hkd"], "2000")
        self.assertEqual(by_name["HKT Enterprise official Telecommunications Backup Service - Smartline iBCP 26-50 Lines tariff 2013-06-01"]["monthly_fee_hkd"], "6000")
        self.assertIn("setup, external removal, extra activation", rows[0]["add_on_charges_hkd"])

    def test_extracts_hkt_official_eye_service_tariff_pdf_row(self) -> None:
        source = {
            "source_id": "hkt_eye_service_tariff_20140516",
            "brand": "HKT",
            "product_category": "official_tariff_eye_service",
            "url": "https://www.hkt.com/api-service/assets/U0025-012-May2014-R%20eye%20Service.pdf",
            "official_source_type": "official_public_tariff_pdf",
            "published_on": "2014-05-16",
        }
        result = {
            "url": source["url"],
            "final_url": source["url"],
            "status": 200,
            "content_type": "application/pdf",
            "bytes": len(HKT_EYE_SERVICE_TARIFF_2014_TEXT),
            "title": "PDF",
            "text": HKT_EYE_SERVICE_TARIFF_2014_TEXT,
            "error": "",
            "method": "fake_pdf",
        }
        rows = _parse_hkt_eye_service_tariff_pdf(source, result, "2026-07-07T00:00:00+08:00")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["monthly_fee_hkd"], "888")
        self.assertIn("eye Service core", rows[0]["plan_name"])
        self.assertIn("not written as main monthly fee", rows[0]["add_on_charges_hkd"])

    def test_extracts_hkt_official_eye_communication_package_tariff_pdf_row(self) -> None:
        source = {
            "source_id": "hkt_eye_communication_package_tariff_20130530",
            "brand": "HKT",
            "product_category": "official_tariff_eye_service",
            "url": "https://www.hkt.com/api-service/assets/U0025-013-May2013-R%20eye%20Communicat.pdf",
            "official_source_type": "official_public_tariff_pdf",
            "published_on": "2013-05-30",
        }
        result = {
            "url": source["url"],
            "final_url": source["url"],
            "status": 200,
            "content_type": "application/pdf",
            "bytes": len(HKT_EYE_COMMUNICATION_PACKAGE_TARIFF_2013_TEXT),
            "title": "PDF",
            "text": HKT_EYE_COMMUNICATION_PACKAGE_TARIFF_2013_TEXT,
            "error": "",
            "method": "fake_pdf",
        }
        rows = _parse_hkt_eye_service_tariff_pdf(source, result, "2026-07-08T00:00:00+08:00")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["monthly_fee_hkd"], "888")
        self.assertIn("eye Communication Package core", rows[0]["plan_name"])
        self.assertIn("Connection charge", rows[0]["evidence_excerpt"])

    def test_extracts_hkt_official_eye_home_smartphone_tariff_pdf_rows(self) -> None:
        source = {
            "source_id": "hkt_eye_home_smartphone_tariff_20120910",
            "brand": "HKT",
            "product_category": "official_tariff_eye_home_smartphone",
            "url": "https://www.hkt.com/api-service/assets/U025-013-Sep2012-R%20eye%20Home%20Smartp.pdf",
            "official_source_type": "official_public_tariff_pdf",
            "published_on": "2012-09-10",
        }
        text = (
            "eye Home Smartphone Package Amount of Charges (HK$) eye Home Smartphone voice call access "
            "to Infotainment Services SMS and local video call 888 or more per month. "
            "Parallel extension phone line Monthly rental (where applicable) 298."
        )
        result = {"url": source["url"], "final_url": source["url"], "status": 200, "text": text}
        rows = _parse_hkt_eye_home_smartphone_tariff_pdf(source, result, "2026-07-10T00:00:00+08:00")

        self.assertEqual(len(rows), 2)
        self.assertEqual([row["monthly_fee_hkd"] for row in rows], ["888", "298"])
        self.assertIn("core service", rows[0]["plan_name"])
        self.assertIn("parallel extension", rows[1]["plan_name"])

    def test_extracts_hkt_official_eye_home_smartphone_2011_tariff_pdf_rows(self) -> None:
        source = {
            "source_id": "hkt_eye_home_smartphone_tariff_20111101",
            "brand": "HKT",
            "product_category": "official_tariff_eye_home_smartphone",
            "url": "https://www.hkt.com/api-service/assets/U025_032_eye_Home_Smartphone_Packa.pdf",
            "official_source_type": "official_public_tariff_pdf",
            "published_on": "2011-11-01",
        }
        text = (
            "eye Home Smartphone Package eye Line and access to Information Services $ 258 or more per month. "
            "Parallel phone line (a) Monthly rental $ 110."
        )
        result = {"url": source["url"], "final_url": source["url"], "status": 200, "text": text}
        rows = _parse_hkt_eye_home_smartphone_tariff_pdf(source, result, "2026-07-10T00:00:00+08:00")

        self.assertEqual([row["monthly_fee_hkd"] for row in rows], ["258", "110"])

    def test_extracts_hkt_official_eye_multimedia_service_2012_tariff_pdf_rows(self) -> None:
        source = {
            "source_id": "hkt_eye_multimedia_service_tariff_20120910",
            "brand": "HKT",
            "product_category": "official_tariff_eye_multimedia_service",
            "url": "https://www.hkt.com/api-service/assets/U025-011-Sep2012-R%20eye%20Multimedia%20.pdf",
            "official_source_type": "official_public_tariff_pdf",
            "published_on": "2012-09-10",
        }
        text = (
            "eye Multimedia Service voice call, Infotainment Services, SMS and local video call 888 per month. "
            "Parallel extension phone line Monthly rental (where applicable) 298."
        )
        result = {"url": source["url"], "final_url": source["url"], "status": 200, "text": text}
        rows = _parse_hkt_eye_multimedia_service_tariff_pdf(source, result, "2026-07-10T00:00:00+08:00")

        self.assertEqual([row["monthly_fee_hkd"] for row in rows], ["888", "298"])

    def test_extracts_hkt_official_international_toll_free_2010_tariff_pdf_row(self) -> None:
        source = {
            "source_id": "hkt_international_toll_free_tariff_20100331",
            "brand": "HKT Enterprise",
            "product_category": "official_tariff_international_toll_free",
            "url": "https://www.hkt.com/api-service/assets/F050_0051_Int_l_Toll_Free_Service.pdf",
            "official_source_type": "official_public_tariff_pdf",
            "published_on": "2010-03-31",
        }
        text = "International Toll Free Service Tariffs (HK$) (a) Registration First line $400 (b) Service per month $400 (c) International telephone call per applicable IDD service rates table."
        result = {"url": source["url"], "final_url": source["url"], "status": 200, "text": text}
        rows = _parse_hkt_international_toll_free_tariff_pdf(source, result, "2026-07-10T00:00:00+08:00")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["monthly_fee_hkd"], "400")
        self.assertIn("Registration", rows[0]["add_on_charges_hkd"])

    def test_extracts_hkt_official_super_hotline_2010_tariff_pdf_row(self) -> None:
        source = {"source_id": "hkt_super_hotline_tariff_20101029", "brand": "HKT Enterprise", "product_category": "official_tariff_super_hotline", "url": "https://www.hkt.com/api-service/assets/U025-007_super_hotline.pdf", "official_source_type": "official_public_tariff_pdf", "published_on": "2010-10-29"}
        result = {"url": source["url"], "final_url": source["url"], "status": 200, "text": "Name of Tariff: Super Hotline Setup Charge: $8,000/manday Rental: $1000/port/month Remarks: Customer is required to pay additional charge for IVRS features."}
        rows = _parse_hkt_super_hotline_tariff_pdf(source, result, "2026-07-10T00:00:00+08:00")
        self.assertEqual([row["monthly_fee_hkd"] for row in rows], ["1000"])
        self.assertIn("Setup", rows[0]["add_on_charges_hkd"])

    def test_extracts_hkt_official_faxline_2010_tariff_pdf_rows(self) -> None:
        for service, fee in (("Faxline 100", "31"), ("Faxline 200", "48"), ("Faxline 3", "48"), ("Faxline 2", "31")):
            source = {"source_id": f"test_{service}", "brand": "HKT Enterprise", "product_category": "official_tariff_business_faxline", "url": "https://example.test/fax.pdf", "official_source_type": "official_public_tariff_pdf", "published_on": "2010-12-16"}
            result = {"url": source["url"], "status": 200, "text": f"Name of Tariff: {service} service Charges: HK${fee} per month All customers must subscribe to a business telephone line."}
            rows = _parse_hkt_faxline_tariff_pdf(source, result, "2026-07-10T00:00:00+08:00")
            self.assertEqual([row["monthly_fee_hkd"] for row in rows], [fee])

    def test_extracts_hkt_official_homefax_2010_tariff_pdf_row(self) -> None:
        source = {
            "source_id": "hkt_homefax_1_tariff_20101216",
            "brand": "HKT",
            "product_category": "official_tariff_home_fax_service",
            "url": "https://www.hkt.com/api-service/assets/U025-014%20_revised_Homefax_1_servic.pdf",
            "official_source_type": "official_public_tariff_pdf",
            "published_on": "2010-12-16",
        }
        text = "Homefax 1 service Charges: HK$30 per month. All customers to Homefax 1 must subscribe to a residential telephone exchange line at the same time."
        result = {"url": source["url"], "final_url": source["url"], "status": 200, "text": text}
        rows = _parse_hkt_homefax_1_tariff_pdf(source, result, "2026-07-10T00:00:00+08:00")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["monthly_fee_hkd"], "30")
        self.assertIn("underlying line rental", rows[0]["add_on_charges_hkd"])

    def test_extracts_hkt_official_eye2_2012_tariff_pdf_row(self) -> None:
        source = {
            "source_id": "hkt_eye2_communication_package_tariff_20120910",
            "brand": "HKT",
            "product_category": "official_tariff_eye2_service",
            "url": "https://www.hkt.com/api-service/assets/U025-015-Sep2012-R%20eye2%20communicat.pdf",
            "official_source_type": "official_public_tariff_pdf",
            "published_on": "2012-09-10",
        }
        text = (
            "eye2 Communication Package voice call access to various Infotainment Services SMS and local video call "
            "888 or more per month (It varies depending on subscription of different offers available from Infotainment Service providers.)"
        )
        result = {"url": source["url"], "final_url": source["url"], "status": 200, "text": text}
        rows = _parse_hkt_eye2_communication_package_tariff_pdf(source, result, "2026-07-10T00:00:00+08:00")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["monthly_fee_hkd"], "888")
        self.assertIn("2012-09-10", rows[0]["plan_name"])

    def test_extracts_hkt_official_home_easywatch_tariff_pdf_row(self) -> None:
        source = {
            "source_id": "hkt_home_easywatch_tariff_20130401",
            "brand": "HKT",
            "product_category": "official_tariff_home_monitoring",
            "url": "https://www.hkt.com/api-service/assets/U0025-005-Apr2013-R%20Home%20Easywatch.pdf",
            "official_source_type": "official_public_tariff_pdf",
            "published_on": "2013-04-01",
        }
        result = {
            "url": source["url"],
            "final_url": source["url"],
            "status": 200,
            "content_type": "application/pdf",
            "bytes": len(HKT_HOME_EASYWATCH_TARIFF_2013_TEXT),
            "title": "PDF",
            "text": HKT_HOME_EASYWATCH_TARIFF_2013_TEXT,
            "error": "",
            "method": "fake_pdf",
        }
        rows = _parse_hkt_home_easywatch_tariff_pdf(source, result, "2026-07-07T00:00:00+08:00")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["monthly_fee_hkd"], "498")
        self.assertIn("Home EasyWatch", rows[0]["plan_name"])
        self.assertIn("ceased for new customers", rows[0]["local_voice"])
        self.assertIn("installation/relocation fee HK$2,000", rows[0]["add_on_charges_hkd"])

    def test_extracts_hkt_official_easywatch_commercial_tariff_pdf_row(self) -> None:
        source = {
            "source_id": "hkt_easywatch_commercial_tariff_20140620",
            "brand": "HKT Enterprise",
            "product_category": "official_tariff_commercial_monitoring",
            "url": "https://www.hkt.com/api-service/assets/U0025-014-Jun2014-R%20HKT%20EasyWatch%20.pdf",
            "official_source_type": "official_public_tariff_pdf",
            "published_on": "2014-06-20",
        }
        result = {
            "url": source["url"],
            "final_url": source["url"],
            "status": 200,
            "content_type": "application/pdf",
            "bytes": len(HKT_EASYWATCH_COMMERCIAL_TARIFF_2014_TEXT),
            "title": "PDF",
            "text": HKT_EASYWATCH_COMMERCIAL_TARIFF_2014_TEXT,
            "error": "",
            "method": "fake_pdf",
        }
        rows = _parse_hkt_easywatch_commercial_tariff_pdf(source, result, "2026-07-07T00:00:00+08:00")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["monthly_fee_hkd"], "1500")
        self.assertIn("EasyWatch Commercial Service", rows[0]["plan_name"])
        self.assertIn("storage fee HK$5/GB/month", rows[0]["add_on_charges_hkd"])

    def test_extracts_hkt_official_ip_voice_tariff_pdf_row(self) -> None:
        source = {
            "source_id": "hkt_ip_voice_tariff_20130531",
            "brand": "HKT",
            "product_category": "official_tariff_ip_voice",
            "url": "https://www.hkt.com/api-service/assets/U0025-015-May2013-R%20Internet%20Proto.pdf",
            "official_source_type": "official_public_tariff_pdf",
            "published_on": "2013-05-31",
        }
        result = {
            "url": source["url"],
            "final_url": source["url"],
            "status": 200,
            "content_type": "application/pdf",
            "bytes": len(HKT_IP_VOICE_TARIFF_2013_TEXT),
            "title": "PDF",
            "text": HKT_IP_VOICE_TARIFF_2013_TEXT,
            "error": "",
            "method": "fake_pdf",
        }
        rows = _parse_hkt_ip_voice_tariff_pdf(source, result, "2026-07-07T00:00:00+08:00")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["monthly_fee_hkd"], "298")
        self.assertIn("Internet Protocol Voice Service", rows[0]["plan_name"])
        self.assertIn("Unlimited voice calls", rows[0]["local_voice"])
        self.assertIn("not written as main monthly fee", rows[0]["add_on_charges_hkd"])

    def test_extracts_hkt_official_freedome_network_safety_tariff_pdf_row(self) -> None:
        source = {
            "source_id": "hkt_freedome_network_safety_tariff_20161201",
            "brand": "NETVIGATOR",
            "product_category": "official_tariff_security_software",
            "url": "https://www.hkt.com/api-service/assets/U0025-019-Dec2016-N%20Freedome%20Netwo.pdf",
            "official_source_type": "official_public_tariff_pdf",
            "published_on": "2016-12-01",
        }
        result = {
            "url": source["url"],
            "final_url": source["url"],
            "status": 200,
            "content_type": "application/pdf",
            "bytes": len(HKT_FREEDOME_NETWORK_SAFETY_TARIFF_2016_TEXT),
            "title": "PDF",
            "text": HKT_FREEDOME_NETWORK_SAFETY_TARIFF_2016_TEXT,
            "error": "",
            "method": "fake_pdf",
        }
        rows = _parse_hkt_freedome_network_safety_tariff_pdf(source, result, "2026-07-07T00:00:00+08:00")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["monthly_fee_hkd"], "38")
        self.assertEqual(rows[0]["contract_months"], "24")
        self.assertIn("Freedome Network Safety Software", rows[0]["plan_name"])
        self.assertIn("NETVIGATOR broadband customers", rows[0]["add_on_charges_hkd"])

    def test_extracts_hkt_official_norton_secure_vpn_tariff_pdf_row(self) -> None:
        source = {
            "source_id": "hkt_norton_secure_vpn_tariff_20200601",
            "brand": "NETVIGATOR",
            "product_category": "official_tariff_security_software",
            "url": "https://www.hkt.com/api-service/assets/U0025-004-Jun2020-R%20Norton%20Secure%20.pdf",
            "official_source_type": "official_public_tariff_pdf",
            "published_on": "2020-06-01",
        }
        result = {
            "url": source["url"],
            "final_url": source["url"],
            "status": 200,
            "content_type": "application/pdf",
            "bytes": len(HKT_NORTON_SECURE_VPN_TARIFF_2020_TEXT),
            "title": "PDF",
            "text": HKT_NORTON_SECURE_VPN_TARIFF_2020_TEXT,
            "error": "",
            "method": "fake_pdf",
        }
        rows = _parse_hkt_norton_secure_vpn_tariff_pdf(source, result, "2026-07-07T00:00:00+08:00")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["monthly_fee_hkd"], "28")
        self.assertEqual(rows[0]["contract_months"], "24")
        self.assertIn("Norton Secure VPN", rows[0]["plan_name"])
        self.assertIn("NETVIGATOR broadband customers", rows[0]["add_on_charges_hkd"])

    def test_extracts_hkt_official_eye2_communication_package_tariff_pdf_row(self) -> None:
        source = {
            "source_id": "hkt_eye2_communication_package_tariff_20100927",
            "brand": "HKT",
            "product_category": "official_tariff_eye2_service",
            "url": "https://www.hkt.com/api-service/assets/U025-003%20eye2%20Communication%20Package.pdf",
            "official_source_type": "official_public_tariff_pdf",
            "published_on": "2010-09-27",
        }
        result = {
            "url": source["url"],
            "final_url": source["url"],
            "status": 200,
            "content_type": "application/pdf",
            "bytes": len(HKT_EYE2_COMMUNICATION_PACKAGE_TARIFF_2010_TEXT),
            "title": "PDF",
            "text": HKT_EYE2_COMMUNICATION_PACKAGE_TARIFF_2010_TEXT,
            "error": "",
            "method": "fake_pdf",
        }
        rows = _parse_hkt_eye2_communication_package_tariff_pdf(source, result, "2026-07-07T00:00:00+08:00")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["monthly_fee_hkd"], "278")
        self.assertIn("eye2 Communication Package", rows[0]["plan_name"])
        self.assertIn("lower bound", rows[0]["add_on_charges_hkd"])
        self.assertIn("varies by Information Service provider offers", rows[0]["add_on_charges_hkd"])

    def test_extracts_hkt_official_severe_weather_warning_tariff_pdf_rows(self) -> None:
        source = {
            "source_id": "hkt_severe_weather_warning_tariff_20110124",
            "brand": "HKT",
            "product_category": "official_tariff_severe_weather_warning",
            "url": "https://www.hkt.com/api-service/assets/U025_020_Severe_Weather_Warning_se.pdf",
            "official_source_type": "official_public_tariff_pdf",
            "published_on": "2011-01-24",
        }
        result = {
            "url": source["url"],
            "final_url": source["url"],
            "status": 200,
            "content_type": "application/pdf",
            "bytes": len(HKT_SEVERE_WEATHER_WARNING_TARIFF_2011_TEXT),
            "title": "PDF",
            "text": HKT_SEVERE_WEATHER_WARNING_TARIFF_2011_TEXT,
            "error": "",
            "method": "fake_pdf",
        }
        rows = _parse_hkt_severe_weather_warning_tariff_pdf(source, result, "2026-07-07T00:00:00+08:00")

        self.assertEqual(len(rows), 3)
        self.assertEqual([row["monthly_fee_hkd"] for row in rows], ["90", "220", "90"])
        self.assertEqual({row["contract_months"] for row in rows}, {"12"})
        self.assertTrue(all("registration HK$300" in row["add_on_charges_hkd"] for row in rows))
        self.assertIn("thunderstorm warning announcement", {row["plan_name"].split(" - ", 1)[1].rsplit(" HK$", 1)[0] for row in rows})

    def test_extracts_hkt_official_customer_voice_hotline_tariff_pdf_row(self) -> None:
        source = {
            "source_id": "hkt_customer_voice_hotline_tariff_20130601",
            "brand": "HKT Enterprise",
            "product_category": "official_tariff_customer_voice_hotline",
            "url": "https://www.hkt.com/api-service/assets/U0025-017-Jun2013-R%20Customer%20voice.pdf",
            "official_source_type": "official_public_tariff_pdf",
            "published_on": "2013-06-01",
        }
        result = {
            "url": source["url"],
            "final_url": source["url"],
            "status": 200,
            "content_type": "application/pdf",
            "bytes": len(HKT_CUSTOMER_VOICE_HOTLINE_TARIFF_2013_TEXT),
            "title": "PDF",
            "text": HKT_CUSTOMER_VOICE_HOTLINE_TARIFF_2013_TEXT,
            "error": "",
            "method": "fake_pdf",
        }
        rows = _parse_hkt_customer_voice_hotline_tariff_pdf(source, result, "2026-07-08T00:00:00+08:00")

        self.assertEqual(len(rows), 3)
        by_fee = {row["monthly_fee_hkd"]: row for row in rows}
        self.assertEqual(set(by_fee), {"2500", "2800", "1000"})
        self.assertIn("Service port/user or telephone line", by_fee["2500"]["plan_name"])
        self.assertIn("Call Queue per call queue", by_fee["2800"]["plan_name"])
        self.assertIn("Call Queue per user", by_fee["1000"]["plan_name"])
        self.assertIn("setup charge HK$32,000", by_fee["2500"]["add_on_charges_hkd"])
        self.assertIn("setup/installation charge HK$2,000", by_fee["2800"]["add_on_charges_hkd"])
        self.assertIn("Monthly charge", by_fee["2500"]["evidence_excerpt"])

    def test_extracts_hkt_official_residential_cell_relay_tariff_pdf_rows(self) -> None:
        source = {
            "source_id": "hkt_residential_cell_relay_tariff_20130601",
            "brand": "HKT Enterprise",
            "product_category": "official_tariff_residential_cell_relay",
            "url": "https://www.hkt.com/api-service/assets/U0025-022-Jun2013-R%20CRS%20Services.pdf",
            "official_source_type": "official_public_tariff_pdf",
            "published_on": "2013-06-01",
        }
        result = {
            "url": source["url"],
            "final_url": source["url"],
            "status": 200,
            "content_type": "application/pdf",
            "bytes": len(HKT_RESIDENTIAL_CELL_RELAY_TARIFF_2013_TEXT),
            "title": "PDF",
            "text": HKT_RESIDENTIAL_CELL_RELAY_TARIFF_2013_TEXT,
            "error": "",
            "method": "fake_pdf",
        }
        rows = _parse_hkt_residential_cell_relay_tariff_pdf(source, result, "2026-07-10T00:00:00+08:00")
        by_fee = {row["monthly_fee_hkd"]: row for row in rows}
        self.assertEqual(len(rows), 18)
        self.assertEqual(by_fee["150"]["post_fup_speed_mbps"], "1.5")
        self.assertEqual(by_fee["78000"]["post_fup_speed_mbps"], "1000")
        self.assertEqual(by_fee["2000"]["post_fup_speed_mbps"], "")
        self.assertTrue(all(row["extraction_status"] == "parsed_official_tariff_pdf" for row in rows))
        self.assertTrue(all("Installation, internal/external relocation" in row["add_on_charges_hkd"] for row in rows))

    def test_extracts_hkt_official_megalink_plus_tariff_pdf_rows(self) -> None:
        source = {
            "source_id": "hkt_megalink_plus_tariff_20130514",
            "brand": "HKT Enterprise",
            "product_category": "official_tariff_megalink_plus",
            "url": "https://www.hkt.com/api-service/assets/U0025-011-May2013-R%20Megalink%20Plus.pdf",
            "official_source_type": "official_public_tariff_pdf",
            "published_on": "2013-05-14",
        }
        result = {
            "url": source["url"],
            "final_url": source["url"],
            "status": 200,
            "content_type": "application/pdf",
            "bytes": len(HKT_MEGALINK_PLUS_TARIFF_2013_TEXT),
            "title": "PDF",
            "text": HKT_MEGALINK_PLUS_TARIFF_2013_TEXT,
            "error": "",
            "method": "fake_pdf",
        }
        rows = _parse_hkt_megalink_plus_tariff_pdf(source, result, "2026-07-10T00:00:00+08:00")
        by_fee = {row["monthly_fee_hkd"]: row for row in rows}
        self.assertEqual(len(rows), 6)
        self.assertEqual(by_fee["22100"]["post_fup_speed_mbps"], "10")
        self.assertEqual(by_fee["162500"]["post_fup_speed_mbps"], "1000")
        self.assertEqual(by_fee["5000"]["post_fup_speed_mbps"], "8")
        self.assertTrue(all(row["extraction_status"] == "parsed_official_tariff_pdf" for row in rows))

    def test_extracts_hkt_official_megalink_plus_2008_tariff_pdf_rows(self) -> None:
        source = {
            "source_id": "hkt_megalink_plus_tariff_20081128",
            "brand": "HKT Enterprise",
            "product_category": "official_tariff_megalink_plus",
            "url": "https://www.hkt.com/api-service/assets/F050-0007%20Megalink%20Plus.pdf",
            "official_source_type": "official_public_tariff_pdf",
            "published_on": "2008-11-28",
        }
        result = {
            "url": source["url"],
            "final_url": source["url"],
            "status": 200,
            "content_type": "application/pdf",
            "bytes": len(HKT_MEGALINK_PLUS_TARIFF_2008_TEXT),
            "title": "PDF",
            "text": HKT_MEGALINK_PLUS_TARIFF_2008_TEXT,
            "error": "",
            "method": "fake_pdf",
        }
        rows = _parse_hkt_megalink_plus_tariff_pdf(source, result, "2026-07-10T00:00:00+08:00")
        by_fee = {row["monthly_fee_hkd"]: row for row in rows}
        self.assertEqual(len(rows), 16)
        self.assertEqual(by_fee["5000"]["post_fup_speed_mbps"], "2")
        self.assertEqual(by_fee["55000"]["post_fup_speed_mbps"], "100")
        self.assertEqual(by_fee["1500"]["post_fup_speed_mbps"], "1.5")

    def test_extracts_hkt_official_ip_net_tariff_pdf_rows(self) -> None:
        source = {
            "source_id": "hkt_ip_net_tariff_20130320",
            "brand": "HKT Enterprise",
            "product_category": "official_tariff_ip_net",
            "url": "https://www.hkt.com/api-service/assets/U0025-004-Mar2013-R%20IP-Net.pdf",
            "official_source_type": "official_public_tariff_pdf",
            "published_on": "2013-03-20",
        }
        result = {
            "url": source["url"], "final_url": source["url"], "status": 200,
            "content_type": "application/pdf", "bytes": len(HKT_IP_NET_TARIFF_2013_TEXT),
            "title": "PDF", "text": HKT_IP_NET_TARIFF_2013_TEXT, "error": "", "method": "fake_pdf",
        }
        rows = _parse_hkt_ip_net_tariff_pdf(source, result, "2026-07-10T00:00:00+08:00")
        by_fee = {row["monthly_fee_hkd"]: row for row in rows}
        self.assertEqual(len(rows), 19)
        self.assertEqual(by_fee["9100"]["post_fup_speed_mbps"], "10")
        self.assertEqual(by_fee["148200"]["post_fup_speed_mbps"], "1000")
        self.assertTrue(all(row["extraction_status"] == "parsed_official_tariff_pdf" for row in rows))

    def test_extracts_hkt_official_integrated_digital_access_tariff_pdf_rows(self) -> None:
        source = {
            "source_id": "hkt_integrated_digital_access_tariff_20250721",
            "brand": "HKT Enterprise",
            "product_category": "official_tariff_integrated_digital_access",
            "url": "https://www.hkt.com/api-service/assets/U0025-001-Jul2025-R_IDA_Service.pdf",
            "official_source_type": "official_public_tariff_pdf",
            "published_on": "2025-07-18",
            "effective_from": "2025-07-21",
        }
        result = {
            "url": source["url"],
            "final_url": source["url"],
            "status": 200,
            "content_type": "application/pdf",
            "bytes": len(HKT_IDA_SERVICE_TARIFF_2025_TEXT),
            "title": "PDF",
            "text": HKT_IDA_SERVICE_TARIFF_2025_TEXT,
            "error": "",
            "method": "fake_pdf",
        }
        rows = _parse_hkt_integrated_digital_access_tariff_pdf(source, result, "2026-07-07T00:00:00+08:00")

        self.assertEqual(len(rows), 3)
        self.assertEqual({row["monthly_fee_hkd"] for row in rows}, {"20000"})
        self.assertEqual(
            {row["plan_name"].split(" - ", 1)[1].split(" tariff", 1)[0] for row in rows},
            {"IDA-P Line", "IDA-M Line", "Priority IDA line"},
        )
        self.assertTrue(all("VAS monthly charges" in row["add_on_charges_hkd"] for row in rows))

    def test_extracts_hkt_official_consumer_fixed_line_tariff_pdf_rows(self) -> None:
        source = {
            "source_id": "hkt_home_phone_tariff_20200210",
            "brand": "HKT",
            "product_category": "official_tariff_consumer_fixed_line",
            "url": "https://www.hkt.com/api-service/assets/U0025-002-Feb2020-R%20Home%20Phone%20Ser.pdf",
            "official_source_type": "official_public_tariff_pdf",
            "published_on": "2020-02-10",
        }
        result = {
            "url": source["url"],
            "final_url": source["url"],
            "status": 200,
            "content_type": "application/pdf",
            "bytes": len(HKT_CONSUMER_FIXED_LINE_TARIFF_TEXT),
            "title": "PDF",
            "text": HKT_CONSUMER_FIXED_LINE_TARIFF_TEXT,
            "error": "",
            "method": "fake_pdf",
        }
        rows = _parse_hkt_consumer_fixed_line_tariff_pdf(source, result, "2026-07-07T00:00:00+08:00")
        by_fee = {row["monthly_fee_hkd"]: row for row in rows}

        self.assertEqual(len(rows), 2)
        self.assertIn("Residential line rental", by_fee["298"]["plan_name"])
        self.assertIn("VAS per feature", by_fee["50"]["plan_name"])
        self.assertIn("one-off items", by_fee["298"]["add_on_charges_hkd"])

    def test_extracts_csl_official_2g_3g_4g_mobile_tariff_pdf_rows(self) -> None:
        source = {
            "source_id": "csl_mobile_2g_3g_4g_tariff_20140919",
            "brand": "csl",
            "product_category": "official_tariff_mobile_2g_3g_4g",
            "url": "https://www.hkt.com/api-service/assets/U0003-001-Sep2014-R%202G%203G%204G%20Mobil.pdf",
            "official_source_type": "official_public_tariff_pdf",
            "published_on": "2014-09-19",
        }
        result = {
            "url": source["url"],
            "final_url": source["url"],
            "status": 200,
            "content_type": "application/pdf",
            "bytes": len(CSL_2G_3G_4G_TARIFF_2014_TEXT),
            "title": "PDF",
            "text": CSL_2G_3G_4G_TARIFF_2014_TEXT,
            "error": "",
            "method": "fake_pdf",
        }
        rows = _parse_csl_2g_3g_4g_mobile_tariff_pdf(source, result, "2026-07-07T00:00:00+08:00")
        by_fee = {row["monthly_fee_hkd"]: row for row in rows}

        self.assertEqual(len(rows), 2)
        self.assertIn("SIM-only Plan", by_fee["600"]["plan_name"])
        self.assertIn("Handset/Tablet Plan", by_fee["750"]["plan_name"])
        self.assertEqual(by_fee["600"]["local_data_gb"], "0.1")
        self.assertIn("HK$40/100MB", by_fee["750"]["add_on_charges_hkd"])

    def test_extracts_csl_official_2012_2g_3g_4g_mobile_tariff_pdf_rows(self) -> None:
        source = {
            "source_id": "csl_mobile_2g_3g_4g_tariff_20120503",
            "brand": "csl",
            "product_category": "official_tariff_mobile_2g_3g_4g",
            "url": "https://www.hkt.com/api-service/assets/U003-001-May2012-R.pdf",
            "official_source_type": "official_public_tariff_pdf",
            "published_on": "2012-05-03",
        }
        result = {"url": source["url"], "final_url": source["url"], "status": 200, "text": CSL_2G_3G_4G_TARIFF_2012_TEXT, "method": "fake_pdf"}
        rows = _parse_csl_2g_3g_4g_mobile_tariff_pdf(source, result, "2026-07-07T00:00:00+08:00")
        by_fee = {row["monthly_fee_hkd"]: row for row in rows}

        self.assertEqual(len(rows), 6)
        self.assertEqual(by_fee["199"]["local_data_gb"], "5")
        self.assertEqual(by_fee["238"]["local_data_gb"], "10")
        self.assertIn("3G Multi Smart SIM Plan", by_fee["268"]["plan_name"])
        self.assertIn("Handset/Tablet Plan 10GB", by_fee["429"]["plan_name"])
        self.assertNotIn("12", by_fee)

    def test_extracts_csl_official_2013_2g_3g_4g_mobile_tariff_pdf_rows(self) -> None:
        source = {
            "source_id": "csl_mobile_2g_3g_4g_tariff_20131021",
            "brand": "csl",
            "product_category": "official_tariff_mobile_2g_3g_4g",
            "url": "https://www.hkt.com/api-service/assets/U0003-007-Oct2013-R%202G%203G%204G%20Mobil.pdf",
            "official_source_type": "official_public_tariff_pdf",
            "published_on": "2013-10-21",
        }
        result = {"url": source["url"], "final_url": source["url"], "status": 200, "text": CSL_2G_3G_4G_TARIFF_2013_TEXT, "method": "fake_pdf"}
        rows = _parse_csl_2g_3g_4g_mobile_tariff_pdf(source, result, "2026-07-07T00:00:00+08:00")
        by_fee = {row["monthly_fee_hkd"]: row for row in rows}

        self.assertEqual(len(rows), 2)
        self.assertEqual(by_fee["200"]["local_data_gb"], "1")
        self.assertEqual(by_fee["300"]["local_data_gb"], "1")
        self.assertIn("HK$40/200MB", by_fee["300"]["add_on_charges_hkd"])

    def test_extracts_csl_smart_pama_tariff_pdf_row(self) -> None:
        source = {
            "source_id": "csl_smart_pama_tariff_20170314",
            "brand": "csl",
            "product_category": "official_tariff_senior_mobile_plan",
            "url": "https://www.hkt.com/api-service/assets/U0008-003-Mar2017-N%20Postpaid%20Servi.pdf",
            "official_source_type": "official_public_tariff_pdf",
            "published_on": "2017-03-14",
        }
        result = {
            "url": source["url"],
            "final_url": source["url"],
            "status": 200,
            "content_type": "application/pdf",
            "bytes": len(CSL_SMART_PAMA_TARIFF_2017_TEXT),
            "title": "PDF",
            "text": CSL_SMART_PAMA_TARIFF_2017_TEXT,
            "error": "",
            "method": "fake_pdf",
        }
        rows = _parse_csl_smart_pama_tariff_pdf(source, result, "2026-07-07T00:00:00+08:00")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["monthly_fee_hkd"], "298")
        self.assertEqual(rows[0]["local_data_gb"], "6")
        self.assertIn("residents aged 65 or above", rows[0]["add_on_charges_hkd"])

    def test_extracts_csl_u_plan_tariff_pdf_row(self) -> None:
        source = {
            "source_id": "csl_u_plan_tariff_20170301",
            "brand": "csl",
            "product_category": "official_tariff_student_mobile_plan",
            "url": "https://www.hkt.com/api-service/assets/U0008-001-Mar2017-N%20Postpaid%20Servi.pdf",
            "official_source_type": "official_public_tariff_pdf",
            "published_on": "2017-03-01",
        }
        result = {
            "url": source["url"],
            "final_url": source["url"],
            "status": 200,
            "content_type": "application/pdf",
            "bytes": len(CSL_U_PLAN_TARIFF_2017_TEXT),
            "title": "PDF",
            "text": CSL_U_PLAN_TARIFF_2017_TEXT,
            "error": "",
            "method": "fake_pdf",
        }
        rows = _parse_csl_postpaid_service_plan_tariff_pdf(source, result, "2026-07-07T00:00:00+08:00")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["monthly_fee_hkd"], "298")
        self.assertEqual(rows[0]["local_data_gb"], "6")
        self.assertIn("U-plan student", rows[0]["add_on_charges_hkd"])

    def test_extracts_csl_club_sim_tariff_pdf_row(self) -> None:
        source = {
            "source_id": "csl_club_sim_tariff_20170802",
            "brand": "csl",
            "product_category": "official_tariff_club_sim_mobile_plan",
            "url": "https://www.hkt.com/api-service/assets/U0008-004-Aug2017-N%20Postpaid%20Servi.pdf",
            "official_source_type": "official_public_tariff_pdf",
            "published_on": "2017-08-02",
        }
        result = {
            "url": source["url"],
            "final_url": source["url"],
            "status": 200,
            "content_type": "application/pdf",
            "bytes": len(CSL_CLUB_SIM_TARIFF_2017_TEXT),
            "title": "PDF",
            "text": CSL_CLUB_SIM_TARIFF_2017_TEXT,
            "error": "",
            "method": "fake_pdf",
        }
        rows = _parse_csl_postpaid_service_plan_tariff_pdf(source, result, "2026-07-07T00:00:00+08:00")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["monthly_fee_hkd"], "28")
        self.assertEqual(rows[0]["local_data_gb"], "0.001")
        self.assertIn("100 minutes", rows[0]["local_voice"])
        self.assertIn("The Club SIM", rows[0]["add_on_charges_hkd"])

    def test_extracts_csl_club_sim_revision_status_notes(self) -> None:
        cases = [
            ("2017-09-30", CSL_CLUB_SIM_TARIFF_UNTIL_FURTHER_NOTICE_TEXT, "until further notice"),
            ("2017-10-19", CSL_CLUB_SIM_TARIFF_CEASED_TEXT, "no longer available for subscription"),
        ]
        for published_on, text, expected_note in cases:
            with self.subTest(published_on=published_on):
                source = {
                    "source_id": f"csl_club_sim_tariff_{published_on.replace('-', '')}",
                    "brand": "csl",
                    "product_category": "official_tariff_club_sim_mobile_plan",
                    "url": "https://www.hkt.com/api-service/assets/club-sim-test.pdf",
                    "official_source_type": "official_public_tariff_pdf",
                    "published_on": published_on,
                }
                result = {
                    "url": source["url"],
                    "final_url": source["url"],
                    "status": 200,
                    "content_type": "application/pdf",
                    "bytes": len(text),
                    "title": "PDF",
                    "text": text,
                    "error": "",
                    "method": "fake_pdf",
                }
                rows = _parse_csl_postpaid_service_plan_tariff_pdf(source, result, "2026-07-07T00:00:00+08:00")

                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["monthly_fee_hkd"], "28")
                self.assertEqual(rows[0]["local_data_gb"], "0.001")
                self.assertIn(expected_note, rows[0]["add_on_charges_hkd"])

    def test_extracts_csl_1010_postpaid_mobile_tariff_pdf_rows(self) -> None:
        source = {
            "source_id": "csl_1010_three_postpaid_tariff_20180822",
            "brand": "csl / 1O1O",
            "product_category": "official_tariff_postpaid_mobile_plan",
            "url": "https://www.hkt.com/api-service/assets/U0008-002-Aug2018-R%20Three%20Postpaid.pdf",
            "official_source_type": "official_public_tariff_pdf",
            "published_on": "2018-08-22",
        }
        result = {
            "url": source["url"],
            "final_url": source["url"],
            "status": 200,
            "content_type": "application/pdf",
            "bytes": len(CSL_1010_POSTPAID_TARIFF_2018_TEXT),
            "title": "PDF",
            "text": CSL_1010_POSTPAID_TARIFF_2018_TEXT,
            "error": "",
            "method": "fake_pdf",
        }
        rows = _parse_csl_1010_postpaid_mobile_tariff_pdf(source, result, "2026-07-07T00:00:00+08:00")
        by_plan = {row["plan_name"]: row for row in rows}

        self.assertEqual(len(rows), 9)
        self.assertEqual(Counter(row["brand"] for row in rows), {"csl": 7, "1O1O": 2})
        self.assertTrue(any(row["monthly_fee_hkd"] == "138" and row["local_data_gb"] == "5" for row in rows))
        self.assertTrue(any(row["monthly_fee_hkd"] == "220" and row["local_data_gb"] == "6" for row in rows))
        self.assertTrue(any(row["brand"] == "1O1O" and row["monthly_fee_hkd"] == "877" and row["roaming_data_gb"] == "10" for row in rows))
        self.assertTrue(any(row["monthly_fee_hkd"] == "818" and row["roaming_data_gb"] == "10" for row in rows))
        self.assertIn("not treated as main plan monthly fee", next(iter(by_plan.values()))["add_on_charges_hkd"])

    def test_extracts_hkt_sme_5g_business_mobile_rows(self) -> None:
        source = {
            "source_id": "hkt_sme_5g_business_mobile",
            "brand": "HKT SME",
            "product_category": "business_mobile_5g",
            "url": "https://www.hkt-sme.com/en/5g-business-mobile/",
            "official_source_type": "official_public_product_page",
        }
        result = {
            "url": source["url"],
            "final_url": source["url"],
            "status": 200,
            "content_type": "text/html",
            "bytes": len(HKT_SME_5G_BUSINESS_TEXT),
            "title": "",
            "text": HKT_SME_5G_BUSINESS_TEXT,
            "error": "",
            "method": "fake",
        }
        rows = _parse_hkt_sme_5g_business_mobile(source, result, "2026-07-06T00:00:00+08:00")
        by_fee = {row["monthly_fee_hkd"]: row for row in rows}

        self.assertEqual(len(rows), 3)
        self.assertEqual(by_fee["128"]["local_data_gb"], "30")
        self.assertEqual(by_fee["128"]["roaming_data_gb"], "3")
        self.assertEqual(by_fee["199"]["roaming_data_gb"], "25")
        self.assertEqual(by_fee["104"]["post_fup_speed_mbps"], "0.128")
        self.assertNotIn("18", by_fee)

    def test_extracts_hkt_sme_business_broadband_rows(self) -> None:
        source = {
            "source_id": "hkt_sme_business_broadband",
            "brand": "HKT SME",
            "product_category": "business_broadband",
            "url": "https://www.hkt-sme.com/en/business-broadband/",
            "official_source_type": "official_public_product_page",
        }
        result = {
            "url": source["url"],
            "final_url": source["url"],
            "status": 200,
            "content_type": "text/html",
            "bytes": len(HKT_SME_BUSINESS_BROADBAND_TEXT),
            "title": "",
            "text": HKT_SME_BUSINESS_BROADBAND_TEXT,
            "error": "",
            "method": "fake",
        }
        rows = _parse_hkt_sme_business_broadband(source, result, "2026-07-06T00:00:00+08:00")
        by_category = {row["product_category"]: row for row in rows}

        self.assertEqual(len(rows), 2)
        self.assertEqual(by_category["business_broadband_ftto"]["monthly_fee_hkd"], "198")
        self.assertEqual(by_category["business_broadband_ftto"]["post_fup_speed_mbps"], "100000")
        self.assertEqual(by_category["business_broadband_5g"]["monthly_fee_hkd"], "198")
        self.assertIn("starting price only", by_category["business_broadband_5g"]["add_on_charges_hkd"])

    def test_extracts_1010_infinite_entertainment_rows(self) -> None:
        source = {
            "source_id": "1010_infinite_entertainment_5g_prestige",
            "brand": "1O1O",
            "product_category": "mobile_prestige_5g_entertainment",
            "url": "https://1010.com.hk/en/infinite-entertainment-5g-prestige-service",
            "official_source_type": "official_public_product_page",
        }
        result = {
            "url": source["url"],
            "final_url": source["url"],
            "status": 200,
            "content_type": "text/html",
            "bytes": len(TEN_TEN_INFINITE_ENTERTAINMENT_TEXT),
            "title": "",
            "text": TEN_TEN_INFINITE_ENTERTAINMENT_TEXT,
            "error": "",
            "method": "fake",
        }
        rows = _parse_1010_infinite_entertainment(source, result, "2026-07-06T00:00:00+08:00")
        by_fee = {row["monthly_fee_hkd"]: row for row in rows}

        self.assertEqual(len(rows), 2)
        self.assertEqual(by_fee["509"]["local_data_gb"], "500")
        self.assertEqual(by_fee["559"]["roaming_data_gb"], "3")
        self.assertEqual(by_fee["559"]["contract_months"], "24/36")
        self.assertNotIn("18", by_fee)

    def test_extracts_old_csl_horizontal_data_voice_table(self) -> None:
        snapshot = {
            "snapshot_id": "csl_data_voice_2018",
            "timestamp": "20181029200935",
            "original_url": "https://www.hkcsl.com/en/new-data-and-voice-service-plan/",
            "brand": "csl",
            "product_category": "mobile_consumer_4g",
            "parser": "csl_old_data_voice",
        }
        result = {
            "url": snapshot["original_url"],
            "final_url": snapshot["original_url"],
            "status": 200,
            "text": CSL_OLD_HORIZONTAL_TEXT,
            "method": "fake",
        }
        rows = _parse_csl_old_data_voice(snapshot, result, "2026-07-06T00:00:00+08:00")
        by_fee = {row["monthly_fee_hkd"]: row for row in rows}

        self.assertEqual(len(rows), 8)
        self.assertEqual(by_fee["158"]["local_data_gb"], "5")
        self.assertEqual(by_fee["198"]["local_data_gb"], "8")
        self.assertEqual(by_fee["298"]["local_data_gb"], "5")
        self.assertEqual(by_fee["738"]["local_data_gb"], "20")

    def test_extracts_pccw_mobile_2010_3g_tariff_table(self) -> None:
        snapshot = {
            "snapshot_id": "pccw_mobile_3g_tariff_20100107",
            "timestamp": "20100107113043",
            "original_url": "http://www2.pccwmobile.com/portal/gen/WEB/home/Services_And_Pricing/tariff/3G-tariff-plan.jsp",
            "brand": "csl",
            "product_category": "mobile_consumer_3g",
            "parser": "pccw_mobile_3g_tariff",
        }
        result = {
            "url": snapshot["original_url"],
            "final_url": snapshot["original_url"],
            "status": 200,
            "text": PCCW_MOBILE_3G_TEXT,
            "method": "fake",
        }
        rows = _parse_pccw_mobile_3g_tariff(snapshot, result, "2026-07-07T00:00:00+08:00")
        by_fee = {row["monthly_fee_hkd"]: row for row in rows}

        self.assertEqual(len(rows), 4)
        self.assertEqual(by_fee["138"]["archive_year"], "2010")
        self.assertIn("600 voice call mins", by_fee["138"]["local_voice"])
        self.assertIn("10000 voice call mins", by_fee["498"]["local_voice"])
        self.assertNotIn("12", by_fee)

    def test_extracts_pccw_mobile_2010_2g_99_tariff_table(self) -> None:
        snapshot = {
            "snapshot_id": "pccw_mobile_2g_99_tariff_20100107",
            "timestamp": "20100107204901",
            "original_url": "http://www2.pccwmobile.com/portal/gen/WEB/home/Services_And_Pricing/tariff/2G_99_Integrated_Minutes_Monthly_Tariff_Plan.jsp",
            "brand": "csl",
            "product_category": "mobile_consumer_2g",
            "parser": "pccw_mobile_2g_99_tariff",
        }
        result = {
            "url": snapshot["original_url"],
            "final_url": snapshot["original_url"],
            "status": 200,
            "text": PCCW_MOBILE_2G_99_TEXT,
            "method": "fake",
        }
        rows = _parse_pccw_mobile_2g_99_tariff(snapshot, result, "2026-07-07T00:00:00+08:00")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["monthly_fee_hkd"], "99")
        self.assertEqual(rows[0]["contract_months"], "12")
        self.assertIn("999 peak-hour", rows[0]["local_voice"])
        self.assertIn("9000 off-peak", rows[0]["local_voice"])
        self.assertNotEqual(rows[0]["monthly_fee_hkd"], "12")
        self.assertNotEqual(rows[0]["monthly_fee_hkd"], "300")

    def test_extracts_pccw_mobile_2010_other_3g_tariff_table(self) -> None:
        snapshot = {
            "snapshot_id": "pccw_mobile_other_3g_tariff_20100107",
            "timestamp": "20100107225908",
            "original_url": "http://www2.pccwmobile.com/portal/gen/WEB/home/Services_And_Pricing/tariff/Other-3G-Tariff-Plan.jsp",
            "brand": "csl",
            "product_category": "mobile_consumer_3g",
            "parser": "pccw_mobile_other_3g_tariff",
        }
        result = {
            "url": snapshot["original_url"],
            "final_url": snapshot["original_url"],
            "status": 200,
            "text": PCCW_MOBILE_OTHER_3G_TEXT,
            "method": "fake",
        }
        rows = _parse_pccw_mobile_other_3g_tariff(snapshot, result, "2026-07-07T00:00:00+08:00")
        by_name = {row["plan_name"]: row for row in rows}

        self.assertEqual(len(rows), 2)
        self.assertTrue(all(row["monthly_fee_hkd"] == "98" for row in rows))
        self.assertIn("3000 voice-call mins", by_name["PCCW mobile historical Other 3G tariff - For Fun Seekers"]["local_voice"])
        self.assertIn("1600 voice-call mins", by_name["PCCW mobile historical Other 3G tariff - For Web Surfers"]["local_voice"])
        self.assertEqual(by_name["PCCW mobile historical Other 3G tariff - For Web Surfers"]["local_data_gb"], "0.1")
        self.assertNotEqual(rows[0]["monthly_fee_hkd"], "12")

    def test_extracts_pccw_mobile_2010_web_talk_tariff_table(self) -> None:
        snapshot = {
            "snapshot_id": "pccw_mobile_web_talk_tariff_20100107",
            "timestamp": "20100107015253",
            "original_url": "http://www2.pccwmobile.com/portal/gen/WEB/home/Services_And_Pricing/tariff/Web-Talk-tariff-plan.jsp?",
            "brand": "csl",
            "product_category": "mobile_consumer_3g",
            "parser": "pccw_mobile_web_talk_tariff",
        }
        result = {
            "url": snapshot["original_url"],
            "final_url": snapshot["original_url"],
            "status": 200,
            "text": PCCW_MOBILE_WEB_TALK_2010_TEXT,
            "method": "fake",
        }
        rows = _parse_pccw_mobile_web_talk_tariff(snapshot, result, "2026-07-07T00:00:00+08:00")
        by_fee = {row["monthly_fee_hkd"]: row for row in rows}

        self.assertEqual(len(rows), 6)
        self.assertEqual(by_fee["98"]["local_data_gb"], "0.1")
        self.assertEqual(by_fee["299"]["local_data_gb"], "0.5")
        self.assertEqual(by_fee["399"]["local_data_gb"], "")
        self.assertEqual(by_fee["478"]["contract_months"], "12")
        self.assertIn("unlimited data", by_fee["399"]["local_voice"])
        self.assertNotIn("12", by_fee)

    def test_extracts_pccw_mobile_2012_web_talk_tariff_table(self) -> None:
        snapshot = {
            "snapshot_id": "pccw_mobile_web_talk_tariff_20120117",
            "timestamp": "20120117052939",
            "original_url": "http://www2.pccwmobile.com/portal/gen/WEB/home/Services_And_Pricing/tariff/Web-Talk-tariff-plan.jsp?",
            "brand": "csl",
            "product_category": "mobile_consumer_3g",
            "parser": "pccw_mobile_web_talk_tariff",
        }
        result = {
            "url": snapshot["original_url"],
            "final_url": snapshot["original_url"],
            "status": 200,
            "text": PCCW_MOBILE_WEB_TALK_2012_TEXT,
            "method": "fake",
        }
        rows = _parse_pccw_mobile_web_talk_tariff(snapshot, result, "2026-07-07T00:00:00+08:00")
        by_fee = {row["monthly_fee_hkd"]: row for row in rows}

        self.assertEqual(len(rows), 9)
        self.assertEqual(by_fee["339"]["local_data_gb"], "5")
        self.assertIn("promotional monthly fee HK$199", by_fee["339"]["add_on_charges_hkd"])
        self.assertIn("SIM-only", by_fee["98"]["add_on_charges_hkd"])
        self.assertEqual(by_fee["198"]["local_data_gb"], "")
        self.assertNotIn("12", by_fee)

    def test_extracts_pccw_mobile_2010_tablet_data_tariff_table(self) -> None:
        snapshot = {
            "snapshot_id": "pccw_mobile_tablet_data_tariff_20100712",
            "timestamp": "20100712111708",
            "original_url": "http://www2.pccwmobile.com/portal/gen/WEB/home/Services_And_Pricing/tariff/Tablet-Mobile-Data-Tariff-Plan.jsp?",
            "brand": "csl",
            "product_category": "mobile_consumer_3g_tablet",
            "parser": "pccw_mobile_tablet_data_tariff",
        }
        result = {"url": snapshot["original_url"], "final_url": snapshot["original_url"], "status": 200, "text": PCCW_MOBILE_TABLET_DATA_TEXT, "method": "fake"}
        rows = _parse_pccw_mobile_tablet_data_tariff(snapshot, result, "2026-07-07T00:00:00+08:00")
        by_fee = {row["monthly_fee_hkd"]: row for row in rows}

        self.assertEqual(len(rows), 2)
        self.assertEqual(by_fee["198"]["contract_months"], "12")
        self.assertEqual(by_fee["328"]["contract_months"], "24")
        self.assertNotIn("50", by_fee)

    def test_extracts_pccw_mobile_free_to_go_sim_only(self) -> None:
        snapshot = {
            "snapshot_id": "pccw_mobile_free_to_go_sim_only_20111007",
            "timestamp": "20111007190459",
            "original_url": "http://www2.pccwmobile.com/portal/gen/WEB/home/Services_And_Pricing/tariff/NEW_Free-to-go_SIM_only_Plan.jsp?",
            "brand": "csl",
            "product_category": "mobile_consumer_3g",
            "parser": "pccw_mobile_free_to_go_sim_only",
        }
        result = {"url": snapshot["original_url"], "final_url": snapshot["original_url"], "status": 200, "text": PCCW_MOBILE_FREE_TO_GO_TEXT, "method": "fake"}
        rows = _parse_pccw_mobile_free_to_go_sim_only(snapshot, result, "2026-07-07T00:00:00+08:00")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["monthly_fee_hkd"], "232")
        self.assertIn("3000 normal", rows[0]["local_voice"])
        self.assertEqual(rows[0]["local_data_gb"], "")

    def test_extracts_pccw_mobile_new_monthly_plan(self) -> None:
        snapshot = {
            "snapshot_id": "pccw_mobile_new_monthly_plan_20120119",
            "timestamp": "20120119212851",
            "original_url": "http://www2.pccwmobile.com/portal/gen/WEB/home/Services_And_Pricing/tariff/New_Monthly_Plan.jsp?",
            "brand": "csl",
            "product_category": "mobile_consumer_3g",
            "parser": "pccw_mobile_new_monthly_plan",
        }
        result = {"url": snapshot["original_url"], "final_url": snapshot["original_url"], "status": 200, "text": PCCW_MOBILE_NEW_MONTHLY_TEXT, "method": "fake"}
        rows = _parse_pccw_mobile_new_monthly_plan(snapshot, result, "2026-07-07T00:00:00+08:00")
        names = {row["plan_name"]: row for row in rows}

        self.assertEqual(len(rows), 11)
        self.assertEqual(names["PCCW mobile historical New Monthly smartphone handset plan HK$389"]["local_data_gb"], "5")
        self.assertEqual(names["PCCW mobile historical New Monthly smartphone SIM special plan HK$98"]["monthly_fee_hkd"], "98")
        self.assertIn("HK$12", rows[0]["add_on_charges_hkd"])

    def test_extracts_pccw_mobile_ultimate_4g_smartphone_plan(self) -> None:
        snapshot = {
            "snapshot_id": "pccw_mobile_ultimate_4g_smartphone_20120507",
            "timestamp": "20120507023051",
            "original_url": "http://www2.pccwmobile.com/portal/gen/WEB/home/Services_And_Pricing/tariff/Ultimate_Mobility_monthly_plan_for_4G_smartphones.jsp",
            "brand": "csl",
            "product_category": "mobile_consumer_4g",
            "parser": "pccw_mobile_ultimate_4g_smartphone",
        }
        result = {"url": snapshot["original_url"], "final_url": snapshot["original_url"], "status": 200, "text": PCCW_MOBILE_ULTIMATE_4G_TEXT, "method": "fake"}
        rows = _parse_pccw_mobile_ultimate_4g_smartphone(snapshot, result, "2026-07-07T00:00:00+08:00")
        by_fee = {row["monthly_fee_hkd"]: row for row in rows}

        self.assertEqual(len(rows), 6)
        self.assertEqual(by_fee["429"]["local_data_gb"], "10")
        self.assertEqual(by_fee["174"]["local_data_gb"], "5")

    def test_extracts_pccw_mobile_multi_smart_sims_plan(self) -> None:
        snapshot = {
            "snapshot_id": "pccw_mobile_multi_smart_sims_20120514",
            "timestamp": "20120514024717",
            "original_url": "http://www2.pccwmobile.com/portal/gen/WEB/home/Services_And_Pricing/tariff/Multi_Smart_SIMs_monthly_plan.jsp?",
            "brand": "csl",
            "product_category": "mobile_consumer_4g",
            "parser": "pccw_mobile_multi_smart_sims",
        }
        result = {"url": snapshot["original_url"], "final_url": snapshot["original_url"], "status": 200, "text": PCCW_MOBILE_MULTI_SMART_SIMS_TEXT, "method": "fake"}
        rows = _parse_pccw_mobile_multi_smart_sims(snapshot, result, "2026-07-07T00:00:00+08:00")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["monthly_fee_hkd"], "268")
        self.assertEqual(rows[0]["contract_months"], "24")
        self.assertEqual(rows[0]["local_data_gb"], "5")

    def test_extracts_pccw_mobile_2g_tariff_plan(self) -> None:
        snapshot = {
            "snapshot_id": "pccw_mobile_2g_tariff_20091017",
            "timestamp": "20091017090534",
            "original_url": "http://www2.pccwmobile.com/portal/gen/WEB/home/Services_And_Pricing/tariff/2G_tariff_plan.jsp?",
            "brand": "csl",
            "product_category": "mobile_consumer_2g",
            "parser": "pccw_mobile_2g_tariff",
        }
        result = {"url": snapshot["original_url"], "final_url": snapshot["original_url"], "status": 200, "text": PCCW_MOBILE_2G_TARIFF_TEXT, "method": "fake"}
        rows = _parse_pccw_mobile_2g_tariff(snapshot, result, "2026-07-07T00:00:00+08:00")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["monthly_fee_hkd"], "88")
        self.assertIn("1200", rows[0]["local_voice"])
        self.assertIn("HK$12", rows[0]["add_on_charges_hkd"])

    def test_extracts_pccw_mobile_cdma_service_plan(self) -> None:
        snapshot = {
            "snapshot_id": "pccw_mobile_cdma_service_20100827",
            "timestamp": "20100827001430",
            "original_url": "http://www2.pccwmobile.com/portal/gen/WEB/home/Services_And_Pricing/tariff/2G_tariff_plan/CDMA_mobile_service.jsp?lang=en",
            "brand": "csl",
            "product_category": "mobile_consumer_cdma",
            "parser": "pccw_mobile_cdma_service",
        }
        result = {"url": snapshot["original_url"], "final_url": snapshot["original_url"], "status": 200, "text": PCCW_MOBILE_CDMA_TEXT, "method": "fake"}
        rows = _parse_pccw_mobile_cdma_service(snapshot, result, "2026-07-07T00:00:00+08:00")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["monthly_fee_hkd"], "3888")
        self.assertEqual(rows[0]["contract_months"], "24")
        self.assertIn("Unlimited local voice-call", rows[0]["local_voice"])
        self.assertEqual(rows[0]["local_data_gb"], "")

    def test_extracts_pccw_mobile_concierge_tariff_plan(self) -> None:
        snapshot = {
            "snapshot_id": "pccw_mobile_concierge_20101017",
            "timestamp": "20101017051803",
            "original_url": "http://www2.pccwmobile.com/portal/gen/WEB/home/Services_And_Pricing/tariff/PCCW_Concierge_service.jsp?",
            "brand": "csl",
            "product_category": "mobile_consumer_3g",
            "parser": "pccw_mobile_concierge",
        }
        result = {"url": snapshot["original_url"], "final_url": snapshot["original_url"], "status": 200, "text": PCCW_MOBILE_CONCIERGE_TEXT, "method": "fake"}
        rows = _parse_pccw_mobile_concierge(snapshot, result, "2026-07-07T00:00:00+08:00")
        by_fee = {row["monthly_fee_hkd"]: row for row in rows}

        self.assertEqual(len(rows), 7)
        self.assertEqual(by_fee["149"]["local_data_gb"], "0.1")
        self.assertEqual(by_fee["249"]["local_data_gb"], "0.5")
        self.assertEqual(by_fee["499"]["local_data_gb"], "")
        self.assertIn("not clear enough", by_fee["499"]["add_on_charges_hkd"])

    def test_extracts_pccw_mobile_netvigator_customer_offer(self) -> None:
        snapshot = {
            "snapshot_id": "pccw_mobile_netvigator_customer_offer_20110413",
            "timestamp": "20110413071106",
            "original_url": "http://www2.pccwmobile.com/portal/gen/WEB/home/Services_And_Pricing/tariff/Special_offer_for_Netvigator_customer.jsp?",
            "brand": "csl",
            "product_category": "mobile_consumer_3g",
            "parser": "pccw_mobile_netvigator_customer_offer",
        }
        result = {"url": snapshot["original_url"], "final_url": snapshot["original_url"], "status": 200, "text": PCCW_MOBILE_NETVIGATOR_CUSTOMER_TEXT, "method": "fake"}
        rows = _parse_pccw_mobile_netvigator_customer_offer(snapshot, result, "2026-07-07T00:00:00+08:00")
        by_fee = {row["monthly_fee_hkd"]: row for row in rows}

        self.assertEqual(len(rows), 3)
        self.assertEqual(by_fee["256"]["contract_months"], "36")
        self.assertEqual(by_fee["288"]["contract_months"], "30")
        self.assertEqual(by_fee["318"]["contract_months"], "24")
        self.assertEqual(by_fee["318"]["local_data_gb"], "1")

    def test_extracts_pccw_mobile_new_ultimate_smartphones_plan(self) -> None:
        snapshot = {
            "snapshot_id": "pccw_mobile_new_ultimate_smartphones_20120915",
            "timestamp": "20120915183828",
            "original_url": "http://www2.pccwmobile.com/portal/gen/WEB/home/Services_And_Pricing/tariff/New_Ultimate_Mobility_Monthly_Plan_for_Smartphones.jsp?",
            "brand": "csl",
            "product_category": "mobile_consumer_4g",
            "parser": "pccw_mobile_new_ultimate_smartphones",
        }
        result = {"url": snapshot["original_url"], "final_url": snapshot["original_url"], "status": 200, "text": PCCW_MOBILE_NEW_ULTIMATE_SMARTPHONES_TEXT, "method": "fake"}
        rows = _parse_pccw_mobile_new_ultimate_smartphones(snapshot, result, "2026-07-07T00:00:00+08:00")
        names = {row["plan_name"]: row for row in rows}

        self.assertEqual(len(rows), 15)
        self.assertEqual(names["PCCW mobile historical New Ultimate Mobility smartphone handset plan HK$489"]["local_data_gb"], "20")
        self.assertEqual(names["PCCW mobile historical New Ultimate Mobility smartphone SIM subscription special monthly fee HK$119"]["local_data_gb"], "1")
        self.assertEqual(names["PCCW mobile historical New Ultimate Mobility smartphone Free-to-go smartphone offer HK$299"]["local_data_gb"], "20")

    def test_extracts_pccw_mobile_new_ultimate_tablets_plan(self) -> None:
        snapshot = {
            "snapshot_id": "pccw_mobile_new_ultimate_tablets_20120914",
            "timestamp": "20120914184631",
            "original_url": "http://www2.pccwmobile.com/portal/gen/WEB/home/Services_And_Pricing/tariff/New_Ultimate_Mobility_Monthly_Plan_for_Tablets.jsp?",
            "brand": "csl",
            "product_category": "mobile_consumer_4g_tablet",
            "parser": "pccw_mobile_new_ultimate_tablets",
        }
        result = {"url": snapshot["original_url"], "final_url": snapshot["original_url"], "status": 200, "text": PCCW_MOBILE_NEW_ULTIMATE_TABLETS_TEXT, "method": "fake"}
        rows = _parse_pccw_mobile_new_ultimate_tablets(snapshot, result, "2026-07-07T00:00:00+08:00")
        names = {row["plan_name"]: row for row in rows}

        self.assertEqual(len(rows), 10)
        self.assertEqual(names["PCCW mobile historical New Ultimate Mobility tablet handset plan HK$459"]["local_data_gb"], "20")
        self.assertEqual(names["PCCW mobile historical New Ultimate Mobility tablet SIM subscription special monthly fee HK$129"]["local_data_gb"], "2.5")
        self.assertEqual(names["PCCW mobile historical New Ultimate Mobility tablet Free-to-go tablet offer HK$269"]["local_data_gb"], "20")

    def test_extracts_old_csl_vertical_data_voice_blocks(self) -> None:
        snapshot = {
            "snapshot_id": "csl_data_voice_2020",
            "timestamp": "20200808094232",
            "original_url": "https://www.hkcsl.com/en/new-data-and-voice-service-plan/",
            "brand": "csl",
            "product_category": "mobile_consumer_4g",
            "parser": "csl_old_data_voice",
        }
        result = {
            "url": snapshot["original_url"],
            "final_url": snapshot["original_url"],
            "status": 200,
            "text": CSL_OLD_VERTICAL_TEXT,
            "method": "fake",
        }
        rows = _parse_csl_old_data_voice(snapshot, result, "2026-07-06T00:00:00+08:00")
        by_plan_fee = {(row["plan_name"], row["monthly_fee_hkd"]): row for row in rows}

        self.assertEqual(len(rows), 6)
        self.assertEqual(by_plan_fee[("csl historical SIM only plan HK$158", "158")]["local_data_gb"], "5")
        self.assertEqual(by_plan_fee[("csl historical SIM only plan HK$198", "198")]["local_data_gb"], "8")
        self.assertEqual(by_plan_fee[("csl historical handset plan HK$298", "298")]["roaming_data_gb"], "")
        self.assertEqual(by_plan_fee[("csl historical handset plan HK$548", "548")]["local_data_gb"], "8")
        self.assertEqual(by_plan_fee[("csl historical handset plan HK$548", "548")]["roaming_data_gb"], "2")

    def test_extracts_2016_2017_csl_ultra_old_data_voice_table(self) -> None:
        snapshot = {
            "snapshot_id": "csl_data_voice_2017",
            "timestamp": "20170110013626",
            "original_url": "https://www.hkcsl.com/en/New-Data-and-Voice-Service-Plan/",
            "brand": "csl",
            "product_category": "mobile_consumer_4g",
            "parser": "csl_old_data_voice",
        }
        result = {
            "url": snapshot["original_url"],
            "final_url": snapshot["original_url"],
            "status": 200,
            "text": CSL_ULTRA_OLD_TEXT,
            "method": "fake",
        }
        rows = _parse_csl_old_data_voice(snapshot, result, "2026-07-06T00:00:00+08:00")
        by_plan_fee = {(row["plan_name"], row["monthly_fee_hkd"]): row for row in rows}
        fees = {row["monthly_fee_hkd"] for row in rows}

        self.assertEqual(len(rows), 8)
        self.assertEqual(by_plan_fee[("csl Ultra 450 historical handset plan HK$298", "298")]["local_data_gb"], "1")
        self.assertEqual(by_plan_fee[("csl Ultra 450 historical SIM only plan HK$238", "238")]["local_data_gb"], "2.5")
        self.assertEqual(by_plan_fee[("csl Ultra 450 historical SIM only plan HK$438", "438")]["local_data_gb"], "10")
        self.assertNotIn("18", fees)
        self.assertNotIn("48", fees)
        self.assertNotIn("50", fees)

    def test_extracts_hkt_enterprise_local_business_telephone_monthly_fees(self) -> None:
        source = {
            "source_id": "hkt_enterprise_local_business_telephone",
            "brand": "HKT Enterprise",
            "product_category": "business_fixed_voice",
            "url": "https://www.hkt-enterprise.com/en/cases-trends/local-business-telephone-services",
            "official_source_type": "official_public_product_page",
        }
        result = {
            "url": source["url"],
            "final_url": source["url"],
            "status": 200,
            "text": HKT_ENTERPRISE_LOCAL_BUSINESS_TELEPHONE_TEXT,
            "method": "fake",
        }
        rows = _parse_hkt_enterprise_local_business_telephone(source, result, "2026-07-06T00:00:00+08:00")
        by_fee = {row["monthly_fee_hkd"]: row for row in rows}

        self.assertGreaterEqual(len(rows), 12)
        self.assertEqual(by_fee["189.80"]["product_category"], "business_fixed_voice")
        self.assertEqual(by_fee["281"]["plan_name"], "HKT Enterprise Local Business Telephone Tone DDI line HK$281")
        self.assertEqual(by_fee["198.8"]["plan_name"], "HKT Enterprise Local Business Telephone Basic Fax HK$198.8")
        self.assertNotIn("600", by_fee)

    def test_extracts_hkt_homephone_value_added_service_monthly_fees(self) -> None:
        source = {
            "source_id": "hkt_homephone_value_added_services_en",
            "brand": "HKT",
            "product_category": "consumer_fixed_voice_vas",
            "url": "http://hkt-homephone.com/vas?lang=eng",
            "official_source_type": "official_public_product_page",
        }
        result = {
            "url": source["url"],
            "final_url": source["url"],
            "status": 200,
            "text": HKT_HOMEPHONE_VALUE_ADDED_SERVICES_TEXT,
            "method": "fake",
        }
        rows = _parse_hkt_homephone_value_added_services(source, result, "2026-07-07T00:00:00+08:00")
        by_fee = {row["monthly_fee_hkd"]: row for row in rows}

        self.assertEqual(len(rows), 10)
        self.assertEqual(by_fee["38"]["plan_name"], "HKT Home Phone OneCall HK$38")
        self.assertEqual(by_fee["27"]["plan_name"], "HKT Home Phone Deluxe Package HK$27")
        self.assertEqual(by_fee["20"]["plan_name"], "HKT Home Phone Call Forwarding HK$20")
        self.assertEqual(by_fee["48"]["plan_name"], "HKT Home Phone Smart Care Voice Reminder Service HK$48")
        self.assertNotIn("0", by_fee)
        self.assertTrue(all(row["extraction_status"] == "parsed" for row in rows))

    def test_extracts_hkt_enterprise_local_business_telephone_tc_monthly_fees(self) -> None:
        source = {
            "source_id": "hkt_enterprise_local_business_telephone_tc",
            "brand": "HKT Enterprise",
            "product_category": "business_fixed_voice",
            "url": "https://www.hkt-enterprise.com/tc/cases-trends/local-business-telephone-services",
            "official_source_type": "official_public_product_page",
        }
        result = {
            "url": source["url"],
            "final_url": source["url"],
            "status": 200,
            "text": HKT_ENTERPRISE_LOCAL_BUSINESS_TELEPHONE_TC_TEXT,
            "method": "fake",
        }
        rows = _parse_hkt_enterprise_local_business_telephone(source, result, "2026-07-06T00:00:00+08:00")
        by_fee = {row["monthly_fee_hkd"]: row for row in rows}

        self.assertGreaterEqual(len(rows), 12)
        self.assertEqual(by_fee["189.80"]["plan_name"], "HKT Enterprise Local Business Telephone Business Telephone line HK$189.80")
        self.assertEqual(by_fee["281"]["plan_name"], "HKT Enterprise Local Business Telephone Tone DDI line HK$281")
        self.assertEqual(by_fee["198.80"]["plan_name"], "HKT Enterprise Local Business Telephone Datel HK$198.80")
        self.assertEqual(by_fee["213"]["plan_name"], "HKT Enterprise Local Business Telephone Citinet HK$213")
        self.assertNotIn("600", by_fee)

    def test_extracts_hkt_local_business_telephone_tariff_pdf_monthly_fees(self) -> None:
        source = {
            "source_id": "hkt_local_business_telephone_tariff_20140109",
            "brand": "HKT Enterprise",
            "product_category": "official_tariff_local_business_telephone",
            "url": "https://www.hkt.com/api-service/assets/U0025-001-Jan2014-R%20Local%20Business.pdf",
            "official_source_type": "official_public_tariff_pdf",
            "published_on": "2014-01-09",
        }
        result = {
            "url": source["url"],
            "final_url": source["url"],
            "status": 200,
            "text": HKT_LOCAL_BUSINESS_TELEPHONE_TARIFF_PDF_TEXT,
            "method": "fake",
        }
        rows = _parse_hkt_local_business_telephone_tariff_pdf(source, result, "2026-07-07T00:00:00+08:00")
        by_plan = {row["plan_name"]: row for row in rows}

        self.assertEqual(len(rows), 7)
        self.assertEqual(
            by_plan["HKT Enterprise official Local Business Telephone tariff 2014-01-09 - Business Telephone Line and Business Select Series"]["monthly_fee_hkd"],
            "300",
        )
        self.assertEqual(
            by_plan["HKT Enterprise official Local Business Telephone tariff 2014-01-09 - Business Citinet Line Series"]["monthly_fee_hkd"],
            "550",
        )
        self.assertEqual(
            by_plan["HKT Enterprise official Local Business Telephone tariff 2014-01-09 - Value-added Services per feature"]["monthly_fee_hkd"],
            "40",
        )
        self.assertNotIn("600", {row["monthly_fee_hkd"] for row in rows})

    def test_hkt_enterprise_5g_broadband_page_stays_source_gap_without_public_price(self) -> None:
        source = {
            "source_id": "hkt_enterprise_5g_business_broadband",
            "brand": "HKT Enterprise",
            "product_category": "business_broadband_5g",
            "url": "https://www.hkt-enterprise.com/en/products-solutions/data-connectivity/business-broadband/solution/5g-broadband",
            "official_source_type": "official_public_product_page",
        }
        result = {
            "url": source["url"],
            "final_url": source["url"],
            "status": 200,
            "text": "5G Broadband Network Internet for Business 1O1O HKT Enterprise Contact Us",
            "method": "fake",
        }
        rows = _parse_source(source, result, "2026-07-06T00:00:00+08:00")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["extraction_status"], "source_fetched_no_plan_rows")
        self.assertEqual(rows[0]["monthly_fee_hkd"], "")

    def test_intentional_product_detail_pages_do_not_parse_non_monthly_fee_amounts(self) -> None:
        cases = [
            (
                "netvigator_5g_home_broadband_plus",
                "NETVIGATOR",
                "home_5g_broadband",
                "https://www.netvigator.com/eng/High-Speed-Home-Broadband-Plus.html",
                "Lost Equipment Fee of HK$4,000 will be charged. The Service is subject to a 250GB monthly data usage.",
            ),
            (
                "hkt_enterprise_business_broadband_overview",
                "HKT Enterprise",
                "business_broadband",
                "https://www.hkt-enterprise.com/en/products-solutions/data-connectivity/business-broadband",
                "HKT Business Broadband 2500M to 50G Fibre Commercial Broadband Contact Us.",
            ),
        ]
        for source_id, brand, category, url, text in cases:
            source = {
                "source_id": source_id,
                "brand": brand,
                "product_category": category,
                "url": url,
                "official_source_type": "official_public_product_page",
            }
            result = {
                "url": source["url"],
                "final_url": source["url"],
                "status": 200,
                "text": text,
                "method": "fake",
            }
            rows = _parse_source(source, result, "2026-07-06T00:00:00+08:00")

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["extraction_status"], "source_fetched_no_plan_rows")
            self.assertEqual(rows[0]["monthly_fee_hkd"], "")

    def test_current_source_failure_preserves_previous_parsed_rows(self) -> None:
        def first_fetcher(_client, url):
            if "1010.com.hk/en/infinite-entertainment" in url:
                text = TEN_TEN_INFINITE_ENTERTAINMENT_TEXT
            elif "hkcsl" in url:
                text = CSL_TEXT
            elif "1010" in url:
                text = TEN_TEN_TEXT
            elif "list-price" in url:
                text = NETVIGATOR_LIST_PRICE_TEXT
            elif "netvigator" in url:
                text = NETVIGATOR_INDEX_TEXT
            elif "hkt-sme" in url:
                text = HKT_SME_5G_BUSINESS_TEXT
            elif "local-business-telephone" in url:
                text = HKT_ENTERPRISE_LOCAL_BUSINESS_TELEPHONE_TEXT
            else:
                text = "HKT Enterprise 5G business mobile product page"
            return {
                "url": url,
                "final_url": url,
                "status": 200,
                "content_type": "text/html",
                "bytes": len(text),
                "title": "",
                "text": text,
                "error": "",
                "method": "fake",
            }

        def second_fetcher(_client, url):
            if "1010.com.hk/en/infinite-entertainment" in url:
                return {
                    "url": url,
                    "final_url": url,
                    "status": 0,
                    "content_type": "",
                    "bytes": 0,
                    "title": "",
                    "text": "",
                    "error": "temporary network failure",
                    "method": "fake_error",
                }
            return first_fetcher(_client, url)

        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            crawl_hkt_products(fetcher=first_fetcher, output_dir=output_dir, include_historical=False)
            crawl_hkt_products(fetcher=second_fetcher, output_dir=output_dir, include_historical=False)
            with (output_dir / "latest_products.csv").open(encoding="utf-8-sig") as fh:
                rows = list(csv.DictReader(fh))

        fallback_rows = [
            row
            for row in rows
            if row["source_id"] == "1010_infinite_entertainment_5g_prestige"
            and row["extraction_status"] == "parsed"
        ]
        gap_rows = [
            row
            for row in rows
            if row["source_id"] == "1010_infinite_entertainment_5g_prestige"
            and row["extraction_status"] == "source_fetched_no_plan_rows"
        ]

        self.assertEqual(len(fallback_rows), 2)
        self.assertEqual({row["fetch_method"] for row in fallback_rows}, {"previous_success_fallback"})
        self.assertEqual(len(gap_rows), 0)

    def test_extracts_1010_ipad_pro_2020_official_product_page_rows(self) -> None:
        cases = [
            """
            iPad Pro 4G Service Plan Mobile fee $529 $609 $799
            Local Mobile Data Usage 6GB+2GB Club 6GB+6GB Club 10GB+10GB Club
            Local Basic Voice Minutes Unlimited. 24-month commitment period.
            """,
            """
            iPad Pro 4G服務計劃 月費 $529 $609 $799
            本地流動數據用量 6GB+2GB 6GB+6GB 10GB+10GB
            本地話音通話分鐘 無限。簽訂24個月承諾期。
            """,
        ]
        source = {
            "source_id": "1010_ipad_pro_2020_test",
            "brand": "1O1O",
            "product_category": "mobile_tablet_data_plan",
            "url": "https://www.1010.com.hk/en/ipad_pro_2020",
            "official_source_type": "official_public_product_page",
        }
        for text in cases:
            with self.subTest(text=text[:20]):
                result = {
                    "url": source["url"],
                    "final_url": source["url"],
                    "status": 200,
                    "text": text,
                    "method": "fake_html",
                }
                rows = _parse_1010_ipad_pro_2020_product_page(source, result, "2026-07-10T00:00:00+08:00")

                self.assertEqual([row["monthly_fee_hkd"] for row in rows], ["529", "609", "799"])
                self.assertEqual([row["local_data_gb"] for row in rows], ["6", "6", "10"])
                self.assertEqual({row["contract_months"] for row in rows}, {"24"})
                self.assertTrue(all("Club member bonus" in row["add_on_charges_hkd"] for row in rows))

    def test_extracts_csl_voip_monthly_pass_without_treating_day_pass_as_monthly(self) -> None:
        source = {
            "source_id": "csl_voip_monthly_pass_tariff_20150720",
            "brand": "csl",
            "product_category": "mobile_voip_service",
            "url": "https://www.hkt.com/api-service/assets/U0008-015-Jul2015-R%20Internet%20Proto.pdf",
            "official_source_type": "official_public_tariff_pdf",
            "published_on": "2015-07-20",
        }
        result = {
            "url": source["url"],
            "final_url": source["url"],
            "status": 200,
            "text": "Internet Protocol V oice Service Basic Charges: Amount (in HK$) Day Pass: $15/day Pay-as-you-use Monthly Pass: $100/month On subscription basis",
            "method": "fake_pdf",
        }
        rows = _parse_csl_voip_monthly_pass_tariff_pdf(source, result, "2026-07-10T00:00:00+08:00")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["monthly_fee_hkd"], "100")
        self.assertIn("Day Pass", rows[0]["add_on_charges_hkd"])

    def test_extracts_1010_kingking_daily_pass_without_populating_monthly_fee(self) -> None:
        snapshot = {
            "snapshot_id": "1010_kingking_voice_roaming_20151005",
            "timestamp": "20151005055017",
            "original_url": "http://1010.hkcsl.com/jsp/roaming_and_idd/kingking/kingking.jsp",
            "brand": "1O1O",
            "product_category": "mobile_voip_daily_pass",
        }
        result = {
            "url": snapshot["original_url"],
            "final_url": snapshot["original_url"],
            "status": 200,
            "text": "KingKing Voice Roaming Service Tariffs For $149 above Service Plans Free Making outgoing voice calls to Hong Kong phone numbers For $148 or below Service Plans $8/day",
            "method": "fake_archive",
        }
        rows = _parse_1010_kingking_voice_roaming(snapshot, result, "2026-07-10T00:00:00+08:00")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["monthly_fee_hkd"], "")
        self.assertEqual(rows[0]["published_price_hkd"], "8")
        self.assertEqual(rows[0]["price_billing_unit"], "day")

    def test_extracts_1010_3g_mobile_tv_standard_package_without_promotional_minutes(self) -> None:
        snapshot = {
            "snapshot_id": "1010_3g_mobile_tv_20090211",
            "timestamp": "20090211055534",
            "original_url": "http://1010.hkcsl.com:80/jsp/3g_service_and_infotainment/3g_mobile_tv/charges_and_subscription/charges_and_subscription.jsp?language=eng",
            "brand": "1O1O",
            "product_category": "mobile_3g_tv_monthly_service",
        }
        result = {
            "url": snapshot["original_url"],
            "final_url": snapshot["original_url"],
            "status": 200,
            "text": "3G Mobile TV Package Monthly Fee Package Includes Thereafter $30 50mins Enjoy total 100 3G Mobile TV minutes now! $1 / min During the promotion period, customer can enjoy total double 3G Mobile TV minutes for the first 12 months and will be resumed to $30/50 3G Mobile TV minutes after the promotion period.",
            "method": "fake_archive",
        }
        rows = _parse_1010_3g_mobile_tv(snapshot, result, "2026-07-10T00:00:00+08:00")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["monthly_fee_hkd"], "30")
        self.assertIn("50 included", rows[0]["local_voice"])
        self.assertIn("promotional doubling", rows[0]["add_on_charges_hkd"])

    def test_extracts_1010_football_monthly_service_packages(self) -> None:
        snapshot = {
            "snapshot_id": "1010_football_service_20080212",
            "timestamp": "20080212083206",
            "original_url": "http://1010.hkcsl.com:80/jsp/3g_service_and_infotainment/football/charges_and_subscription/charges_and_subscription.jsp",
            "brand": "1O1O",
            "product_category": "mobile_football_content_service",
        }
        result = {
            "url": snapshot["original_url"],
            "final_url": snapshot["original_url"],
            "status": 200,
            "text": "Football Channel Package Contents $33 / month Unlimited viewing. Other Package Charge Service Plan League Package Match Schedule and Results $28 Team Package $8 Team Code.",
            "method": "fake_archive",
        }
        rows = _parse_1010_football_service(snapshot, result, "2026-07-10T00:00:00+08:00")

        self.assertEqual([row["monthly_fee_hkd"] for row in rows], ["33", "28", "8"])
        self.assertTrue(all(row["extraction_status"] == "parsed_historical_archive" for row in rows))

    def test_extracts_1010_music_monthly_service_packages(self) -> None:
        snapshot = {
            "snapshot_id": "1010_music_service_20090122",
            "timestamp": "20090122112813",
            "original_url": "http://1010.hkcsl.com:80/jsp/3g_service_and_infotainment/music/charges_and_subscription/charges_and_subscription.jsp",
            "brand": "1O1O",
            "product_category": "mobile_music_content_service",
        }
        result = {
            "url": snapshot["original_url"],
            "final_url": snapshot["original_url"],
            "status": 200,
            "text": "Music Channel Package Including $20 / month 20 MV viewings. Poly/Mono Ringtone + Ringmaster Special Offer# $15. MP3 Ringtone + Ringmaster Special Offer# $25. \"RingMaster\" Power Station# $15 1 Channel $28 2 or above Channels. Self- selected Ringmaster Package# $20. Full Song Download Package $20 3 designated Full Song downloads.",
            "method": "fake_archive",
        }
        rows = _parse_1010_music_service(snapshot, result, "2026-07-10T00:00:00+08:00")

        self.assertEqual([row["monthly_fee_hkd"] for row in rows], ["20", "15", "25", "15", "28", "20", "20"])
        self.assertTrue(all(row["extraction_status"] == "parsed_historical_archive" for row in rows))

    def test_extracts_1010_anyplex_monthly_service_in_english_and_legacy_chinese(self) -> None:
        english_snapshot = {
            "snapshot_id": "1010_anyplex_20140815_en",
            "timestamp": "20140815235737",
            "original_url": "http://1010.hkcsl.com/jsp/3g_service_and_infotainment/anyplex/charges_and_subscription/charges_and_subscription.jsp",
            "brand": "1O1O",
            "product_category": "mobile_movie_voucher_service",
        }
        chinese_snapshot = {**english_snapshot, "snapshot_id": "1010_anyplex_20130807_tc"}
        cases = [
            (english_snapshot, "Anyplex Minimum Contract period Monthly fee Content 12 Months $38 3 movie vouchers per month 24 Months $38 Get one extra movie voucher"),
            (chinese_snapshot, "1O1O 12 month $38 three vouchers 24 month $38 extra vouchers"),
        ]
        for snapshot, text in cases:
            with self.subTest(snapshot=snapshot["snapshot_id"]):
                result = {"url": snapshot["original_url"], "final_url": snapshot["original_url"], "status": 200, "text": text, "method": "fake_archive"}
                rows = _parse_1010_anyplex(snapshot, result, "2026-07-10T00:00:00+08:00")
                self.assertEqual([(row["monthly_fee_hkd"], row["contract_months"]) for row in rows], [("38", "12"), ("38", "24")])


if __name__ == "__main__":
    unittest.main()
