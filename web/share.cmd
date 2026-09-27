@echo off
rem Like start.cmd, but other devices on the same Wi-Fi can open MedMap too.
rem Give them the address printed as "Other devices on the same network".
rem If Windows asks, allow Python through the firewall.
call "%~dp0start.cmd" --host 0.0.0.0
