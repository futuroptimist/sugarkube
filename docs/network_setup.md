# Network Setup

This guide explains how to connect your Pi cluster to a home network.
It assumes you are using Raspberry Pi 5 boards in a small k3s setup.

## Preconfigure WiFi

1. Download and launch [Raspberry Pi Imager](https://www.raspberrypi.com/software/).
2. Press <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>X</kbd> to open **advanced options**.
3. Enter your WiFi **SSID** and **password**, enable **SSH**, and set a unique
   hostname and user for each Pi.
4. Set the wireless LAN **country** to match your location so WiFi channels are enabled correctly.
5. Write the image to an SD card or M.2 drive and repeat for the other boards.
6. Boot each Pi once to confirm it connects. From another machine run
   `ping <hostname>.local` and then `ssh <user>@<hostname>.local` to change the
   default password with `passwd`. If mDNS fails, use the IP shown on your
   router's client list.
7. Reserve a DHCP address for each Pi in your router so their IPs stay
   consistent for the cluster.
8. For SSH logins without a password, generate a key if needed with
   `ssh-keygen -t ed25519`, then copy your public key to each Pi:
   `ssh-copy-id <user>@<hostname>.local`

## Switch and PoE

A gigabit Ethernet switch keeps the cluster stable. If the switch offers
PoE+ (802.3at) you can power the Pis with PoE HATs; otherwise use USB‑C supplies.

## Join the cluster

Boot the control-plane Pi first. Once it appears on your router's client list,
update the OS and install `k3s` on that node as root:

```sh
sudo apt update && sudo apt full-upgrade -y
curl -sfL https://get.k3s.io | sh -

# Ensure the service is running
sudo systemctl status k3s --no-pager

# Wait for the service to report Ready
sudo kubectl get nodes
```

Display the worker join token:

```sh
sudo cat /var/lib/rancher/k3s/server/node-token
```

The token is stored at `/var/lib/rancher/k3s/server/node-token`; copy it for
later.

Boot the remaining Pis once they can reach the control-plane node. Replace
`<server-ip>` with the control-plane's IP and `<node-token>` with the value
above, then run the installer as root:

```sh
curl -sfL https://get.k3s.io | K3S_URL=https://<server-ip>:6443 K3S_TOKEN=<node-token> sh -
```

After the script finishes, confirm the agent service started on the worker:

```sh
sudo systemctl status k3s-agent --no-pager
```

On the control-plane node, watch the cluster recognize each worker as it joins:

```sh
sudo kubectl get nodes -w
```

Press <kbd>Ctrl</kbd>+<kbd>C</kbd> once all nodes show `Ready` to exit the watch.

## Manage from a workstation

To run `kubectl` from your laptop, ensure the
[kubectl client is installed](https://kubernetes.io/docs/tasks/tools/#kubectl).
Copy the kubeconfig generated on the control-plane node (it's owned by
`root`, so fetch it using the `root` account), update its server
address, and verify access:

```sh
mkdir -p ~/.kube
scp root@<server-ip>:/etc/rancher/k3s/k3s.yaml ~/.kube/config
sed -i "s/127.0.0.1/<server-ip>/g" ~/.kube/config
chmod 600 ~/.kube/config
echo "export KUBECONFIG=$HOME/.kube/config" >> ~/.bashrc
source ~/.bashrc
kubectl get nodes
```

The `sed` command swaps the default localhost address for the control-plane
IP. Appending the `KUBECONFIG` line to your shell profile makes the setting
persistent, and `kubectl get nodes` confirms your workstation can reach the
cluster.

See the deployment guide at
[token.place](https://github.com/futuroptimist/token.place) for a detailed
walkthrough. For more options consult the
[k3s quick start](https://docs.k3s.io/quick-start) guide.
