# Network Setup

This guide explains how to connect your Pi cluster to a home network.
It assumes you are using Raspberry Pi 5 boards in a small k3s setup.

## Preconfigure Wi‑Fi

1. Launch **Raspberry Pi Imager** and press <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>X</kbd>.
2. Enter your Wi‑Fi **SSID** and **password** under advanced options.
3. Enable **SSH** and set a unique hostname for each Pi.
4. Write the image to an SD card or M.2 drive and repeat for the other boards.

## Switch and PoE

A gigabit Ethernet switch keeps the cluster stable. If the switch offers
PoE+ you can power the Pis with PoE HATs; otherwise use USB‑C supplies.

## Join the cluster

Boot the control-plane Pi first. Confirm it appears on your router then
install `k3s`. Boot the remaining Pis and join them as workers once they
can ping the control-plane node.

See the deployment guide at
[token.place](https://github.com/futuroptimist/token.place) for a detailed
walkthrough.
