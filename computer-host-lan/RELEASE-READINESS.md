# Computer Host LAN — beta release readiness

| Item | Status |
| --- | --- |
| Separate protocol-v2 project; legacy Linux Host LAN preserved | PASS |
| Gentoo + real SmartThings hub | PASS (hardware tested) |
| Windows x64 compile, HTTP/HMAC tests and LocalService install | PASS (CI only) |
| Windows 11 real SmartThings discovery and WOL | **Open — beta purpose** |
| Linux distro CI | PASS (source/container, not physical hardware) |
| Versioned release packaging and checksums | PASS at `eb277dde`; rerun at final documentation commit |
| GitHub Release | Draft created with four assets; publication pending |
| [SmartThings shared channel](https://bestow-regional.api.smartthings.com/invite/1J2Qy7ZkxL20) | Confirmed; another account installed Computer Host LAN |
| Windows app profile / full LAN device discovery | Unverified, tester target |
| Copyright/third-party provenance | Owner sign-off required |

**Immediate publication sequence:** merge the final documentation update; verify all three CI workflows on the resulting `main` commit; replace four draft release assets and notes from that commit; publish the GitHub prerelease; verify public downloads; then publish the SmartThings Community invitation.

The Windows ZIP is **unsigned**; monitor on a trusted Private LAN only (no HTTP TLS or port forwarding). Power commands stay off by default, and S0/S3/S4/S5 wake is hardware-dependent. The existing `linux-host-lan/` project is not changed or superseded.
