# Network Setup

This guide explains how to connect your Pi cluster to a home network.
It assumes you are using Raspberry Pi 5 boards in a small k3s setup.

## Preconfigure WiFi

1. Download and launch [Raspberry Pi Imager](https://www.raspberrypi.com/software/).
2. Press <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>X</kbd> to open **advanced options**.
3. Enter your WiFi **SSID** and **password**, enable **SSH**, and set a unique hostname and user for each Pi.
4. Set the wireless LAN **country** to match your location so WiFi channels are enabled correctly.
5. Write the image to an SD card or M.2 drive and repeat for the other boards.
6. Boot each Pi once to confirm it connects; `ssh pi@<hostname>.local` and run `passwd` to change the default password.

## Switch and PoE

A gigabit Ethernet switch keeps the cluster stable. If the switch offers
PoE+ (802.3at) you can power the Pis with PoE HATs; otherwise use USB‑C supplies.

## Join the cluster

Boot the control-plane Pi first. Once it shows up on your router's client list,
install `k3s`:

```sh
curl -sfL https://get.k3s.io | sh -
```

Display the worker join token:

```sh
sudo cat /var/lib/rancher/k3s/server/node-token
```

Boot the remaining Pis and join them as workers once they can ping the
control-plane node. Use the token printed on the server (also stored at
`/var/lib/rancher/k3s/server/node-token`):

```sh
curl -sfL https://get.k3s.io | K3S_URL=https://<server-ip>:6443 K3S_TOKEN=<node-token> sh -
```

Verify the cluster:

```sh
sudo kubectl get nodes
```

If you need the token again, view it on the control-plane node:

```sh
sudo cat /var/lib/rancher/k3s/server/node-token
```

## Manage from a workstation

To run `kubectl` from your laptop, copy the kubeconfig generated on the
control-plane node and secure it locally:

```sh
scp pi@<server-ip>:/etc/rancher/k3s/k3s.yaml ~/.kube/config
chmod 600 ~/.kube/config
```

Edit the file and replace the server IP with the control-plane address.
Now `kubectl get nodes` works from your workstation.

See the deployment guide at
[token.place](https://github.com/futuroptimist/token.place) for a detailed
walkthrough. For more options consult the
[k3s quick start](https://docs.k3s.io/quick-start) guide.
