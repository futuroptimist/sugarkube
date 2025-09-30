---
personas:
  - hardware
  - software
---

# Network Setup

This guide explains how to connect your Pi cluster to a home network.
It assumes you are using Raspberry Pi 5 boards in a small k3s setup.

## Preconfigure WiFi

1. Download and launch [Raspberry Pi Imager](https://www.raspberrypi.com/software/).
2. Press <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>X</kbd> to open **advanced options**.
3. Enter your WiFi **SSID** and **password**, enable **SSH**, and set a unique
   hostname and user for each Pi. Optionally paste your SSH public key into the
   *authorized keys* field to allow key-based logins on first boot. To skip
   manual typing, render one of the JSON presets in
   `docs/templates/pi-imager/` with `scripts/render_pi_imager_preset.py` so
   Raspberry Pi Imager opens with your answers pre-filled.
4. Set the wireless LAN **country** to match your location so WiFi channels are enabled correctly.
5. Write the image to an SD card or M.2 drive and repeat for the other boards.
6. Boot each Pi once to confirm it connects. From another machine run
   `ping <hostname>.local` and then `ssh <user>@<hostname>.local` to change the
   default password with `passwd`. If `.local` lookups fail, install an mDNS
   service such as `avahi-daemon` (`sudo apt install avahi-daemon`) or use the
   IP shown on your router's client list. If the router doesn't list it,
   discover the Pi's address with `nmap -sn 192.168.1.0/24`.
7. After logging in, update packages so each Pi starts with the latest fixes:
   `sudo apt update && sudo apt full-upgrade -y`
8. Reboot to ensure kernel updates apply before moving on: `sudo reboot`.
9. Reserve each Pi's MAC address in your router's DHCP table so its IP stays
   consistent even if mDNS stops working. On each board, run
   `ip link show eth0` (or `ip link show wlan0` for WiFi) and note the
   `link/ether` value.
10. If you skipped adding a key earlier, generate one with
    `ssh-keygen -t ed25519`, then copy your public key to each Pi:
    `ssh-copy-id <user>@<hostname>.local`
11. Test key-based login: `ssh <user>@<hostname>.local` should connect without
    prompting for credentials.
12. Harden SSH by disabling password authentication once key-based logins work:
    ```sh
    sudo sed -i 's/^#PasswordAuthentication yes/PasswordAuthentication no/' /etc/ssh/sshd_config
    # Reload the SSH service; some distros use "sshd"
    sudo systemctl reload ssh || sudo systemctl reload sshd
    ```

## Switch and PoE

A gigabit Ethernet switch keeps the cluster stable. If the switch offers
PoE+ (802.3at) you can power the Pis with PoE HATs; otherwise use USB‑C supplies.

## Join the cluster

Boot the control-plane Pi first. Once it appears on your router's client list,
update the OS, disable swap, and install `k3s` on that node as root:

```sh
sudo apt update && sudo apt full-upgrade -y

# Disable swap; k3s refuses to start if swap is active
sudo swapoff -a
sudo sed -i '/ swap / s/^/#/' /etc/fstab

curl -sfL https://get.k3s.io | sudo sh -

# Ensure the service is running
sudo systemctl status k3s --no-pager

# Wait for the service to report Ready
sudo kubectl get nodes
```

Display the worker join token (it is also exported to `/boot/sugarkube-node-token` on
the boot volume for offline recovery):

```sh
sudo cat /var/lib/rancher/k3s/server/node-token
```

The token is stored at `/var/lib/rancher/k3s/server/node-token` and mirrored to the
boot partition. Copy either location for later and guard the value like any other secret.

Boot the remaining Pis once they can reach the control-plane node. On each
worker, disable swap, then install the agent. Replace `<server-ip>` with the
control-plane's IP and `<node-token>` with the value above:

```sh
sudo swapoff -a
sudo sed -i '/ swap / s/^/#/' /etc/fstab

curl -sfL https://get.k3s.io | sudo sh -s - agent \
  --server https://<server-ip>:6443 \
  --token <node-token>
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
Copy the kubeconfig generated on the control-plane node. The image now writes
two variants to the boot volume and also mirrors the k3s join token file.

- `/boot/sugarkube-kubeconfig` (sanitized; secrets redacted).
- `/boot/sugarkube-kubeconfig-full` (full admin credentials).
- `/boot/sugarkube-node-token` (cluster join token for additional agents).

Pull one of these files over SSH (they are owned by `root`) or eject the boot
media and copy the file locally, then update its server address and verify access:

```sh
mkdir -p ~/.kube
scp root@<server-ip>:/boot/sugarkube-kubeconfig-full ~/.kube/config
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

> Tip: You can also grab `/boot/sugarkube-kubeconfig` from the boot volume without SSH.
> The export redacts client keys while preserving cluster endpoints, making it safe to share
> connection details with operators who only need the cluster address and CA bundle.

See the deployment guide at
[token.place](https://github.com/futuroptimist/token.place) for a detailed
walkthrough. For more options consult the
[k3s quick start](https://docs.k3s.io/quick-start) guide.
