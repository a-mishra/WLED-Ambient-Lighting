# Raspberry Pi SD Card

Project: TV Ambient Backlight

Hardware:
- Raspberry Pi Zero 2 W
- Camera v1.3
- WLED Controller

Hostname:
rpi.local

OS:
Raspberry Pi OS Lite (64-bit)

Username: a-mishra
Password: Ash_m812

configured wifi SSID: <home4G>
wifi password: <home4G_password>

Services:
- HyperHDR
- MQTT
- SSH

Static IP: 192.168.1.200

Last Updated:
2026-Jul-08

Notes:
- Camera ribbon connected to CSI port.
- Uses WLED at 192.168.1.210







rpicam-hello --list-cameras
sudo nano /boot/firmware/config.txt
camera_auto_detect=1
dtoverlay=ov5647
sudo reboot
rpicam-hello --list-cameras

(.venv) a-mishra@rpi:~/projects/WLED-Ambient-Lighting $ rpicam-hello --list-cameras
Available cameras
-----------------
0 : ov5647 [2592x1944 10-bit GBRG] (/base/soc/i2c0mux/i2c@1/ov5647@36)
    Modes: 'SGBRG10_CSI2P' : 640x480 [62.50 fps - (16, 0)/2560x1920 crop]
                             1296x972 [46.34 fps - (0, 0)/2592x1944 crop]
                             1920x1080 [32.81 fps - (348, 434)/1928x1080 crop]
                             2592x1944 [15.63 fps - (0, 0)/2592x1944 crop]