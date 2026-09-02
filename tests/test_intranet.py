import unittest
from unittest.mock import patch

from cmhk.intranet import (
    discover_intranet_ipv4_addresses,
    intranet_access_urls,
    is_rfc1918_address,
    parse_ifconfig_ipv4,
)


IFCONFIG_SAMPLE = """\
lo0: flags=8049<UP,LOOPBACK,RUNNING,MULTICAST> mtu 16384
\tinet 127.0.0.1 netmask 0xff000000
en0: flags=8863<UP,BROADCAST,SMART,RUNNING> mtu 1500
\tinet 172.19.2.61 netmask 0xffff0000 broadcast 172.19.255.255
utun4: flags=8051<UP,POINTOPOINT,RUNNING,MULTICAST> mtu 1380
\tinet 198.18.0.1 --> 198.18.0.1 netmask 0xffffffff
bridge100: flags=8863<UP,BROADCAST,SMART,RUNNING> mtu 1500
\tinet 192.168.64.1 netmask 0xffffff00 broadcast 192.168.64.255
"""


class IntranetTest(unittest.TestCase):
    def test_rfc1918_filter_excludes_loopback_and_benchmark_network(self):
        self.assertTrue(is_rfc1918_address("10.20.30.40"))
        self.assertTrue(is_rfc1918_address("172.19.2.61"))
        self.assertTrue(is_rfc1918_address("192.168.1.20"))
        self.assertFalse(is_rfc1918_address("127.0.0.1"))
        self.assertFalse(is_rfc1918_address("198.18.0.1"))

    def test_parse_ifconfig_ipv4_keeps_interface_names(self):
        self.assertEqual(
            parse_ifconfig_ipv4(IFCONFIG_SAMPLE),
            [
                ("lo0", "127.0.0.1"),
                ("en0", "172.19.2.61"),
                ("utun4", "198.18.0.1"),
                ("bridge100", "192.168.64.1"),
            ],
        )

    @patch("cmhk.intranet.subprocess.run")
    @patch("cmhk.intranet.shutil.which", return_value="/sbin/ifconfig")
    def test_discovery_prefers_physical_lan_and_ignores_virtual_adapters(self, _, run):
        run.return_value.stdout = IFCONFIG_SAMPLE
        self.assertEqual(discover_intranet_ipv4_addresses(), ["172.19.2.61"])

    @patch("cmhk.intranet.discover_intranet_ipv4_addresses", return_value=["172.19.2.61"])
    def test_wildcard_host_becomes_shareable_url(self, _):
        self.assertEqual(intranet_access_urls(8765), ["http://172.19.2.61:8765"])


if __name__ == "__main__":
    unittest.main()
