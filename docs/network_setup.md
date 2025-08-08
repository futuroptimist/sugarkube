# Network Setup

This guide explains how to connect your Pi cluster to a home network.
It assumes you are using Raspberry Pi 5 boards in a small k3s setup.

## Preconfigure WiFi

1. Download and launch [Raspberry Pi Imager](https://www.raspberrypi.com/software/).
2. Press <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>X</kbd> to open **advanced options**.
3. Enter your WiFi **SSID** and **password**, enable **SSH**, and set a unique hostname and user for each Pi.
4. Write the image to an SD card or M.2 drive and repeat for the other boards.
5. Boot each Pi once to confirm it connects; `ssh <user>@<hostname>.local` and change the password if prompted.

## Switch and PoE

A gigabit Ethernet switch keeps the cluster stable. If the switch offers
PoE+ (802.3at) you can power the Pis with PoE HATs; otherwise use USB‑C supplies.

## Join the cluster

Boot the control-plane Pi first. After it appears on your router install
`k3s`:

```sh
curl -sfL https://get.k3s.io | sh -
```

Boot the remaining Pis and join them as workers once they can ping the
control-plane node. Use the token printed on the server (also stored at
`/var/lib/rancher/k3s/server/node-token`):

```sh
curl -sfL https://get.k3s.io | K3S_URL=https://<server-ip>:6443 K3S_TOKEN=<node-token> sh -
```

See the deployment guide at
[token.place](https://github.com/futuroptimist/token.place) for a detailed
walkthrough.
