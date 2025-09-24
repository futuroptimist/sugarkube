# Tutorial 3: Networking and the Internet Basics

## Overview
This tutorial grounds you in the networking concepts the Sugarkube roadmap highlights for
[Tutorial 3](./index.md#tutorial-3-networking-and-the-internet-basics). You will learn how your
home network hands out IP addresses, how DNS and routing guide traffic, and how to measure
connectivity using practical command-line tools. Each activity builds the vocabulary and evidence
you need before wiring Raspberry Pis together or exposing services to the wider internet.

By the end you will have a saved network diagram, a latency and bandwidth log, and a practice router
configuration that demonstrates you can interpret traceroute hops, HTTP status codes, and DHCP
reservations.

## Prerequisites
* Complete [Tutorial 1](./tutorial-01-computing-foundations.md) and bring the hardware safety notes.
* Complete [Tutorial 2](./tutorial-02-navigating-linux-terminal.md) so you are comfortable running
  shell commands and capturing transcripts.
* A computer with a terminal (Linux, macOS, or Windows with PowerShell).
* Access to your home router web interface **or** an online router emulator such as the
  [TP-Link TL-WR940N simulator](https://emulator.tp-link.com/tl-wr940nv6_eu/index.html#emulator).
* Optional: a second device (laptop or phone) connected to the same network for end-to-end latency
  checks.

> [!WARNING]
> Always confirm that running diagnostic tools is allowed on the network you are using. If you are
> on a shared or corporate network, request permission before performing latency tests or router
> configuration changes.

## Lab: Map and Test Your Network
Work through the steps in order. Record every screenshot, command output, and note inside a folder
named `sugarkube-tutorial-03` so you can verify milestones later.

### 1. Prepare your documentation workspace
1. Create a new note or document titled `Tutorial 3 Networking Log`.
2. Make a table with columns: *Date/Time*, *Command or Action*, *Result*, *Next Question*.
3. Confirm screen capture is ready (Snipping Tool, macOS Screenshot, or `gnome-screenshot`).

> [!TIP]
> If you prefer structured notes, copy the template from
> [Notion's networking log example](https://www.notion.so/templates/network-log) into your own
> workspace and adapt the columns listed above.

### 2. Discover your local network details
1. Open a terminal and run the commands for your operating system. Capture the output in your log.

   **Linux/macOS (Terminal):**
   ```bash
   hostname
   ip addr show
   ip route
   ```

   **Windows (PowerShell):**
   ```powershell
   hostname
   ipconfig /all
   route print
   ```

2. Highlight the following in your notes:
   * Your computer's IPv4 address.
   * Your default gateway or router address.
   * The DNS servers listed.
3. Run `nslookup sugarkube.io` (PowerShell) or `dig sugarkube.io` (Terminal). Note the IP address
   returned and the DNS server that answered.

> [!NOTE]
> If `dig` is unavailable, install it with `sudo apt install dnsutils` on Debian-based systems or use
> the online [Google Admin Toolbox Dig](https://toolbox.googleapps.com/apps/dig/) and record the
> result.

### 3. Diagram your home network
1. Visit [https://app.diagrams.net](https://app.diagrams.net/) and create a blank drawing.
2. Drag shapes to represent your internet modem, router, switch, computer, and any Raspberry Pis or
   smart devices.
3. Label each connection with the IP address range (for example, `192.168.1.0/24`) and note whether
   the link is Ethernet or Wi-Fi.
4. Export the diagram as `tutorial-03-network-map.png` and save it to your folder.

> [!TIP]
> Add a callout in the diagram for where the Sugarkube enclosure will live physically. This will help
> future tutorials that discuss cabling and rack placement.

### 4. Measure reachability with ping and traceroute
1. In your terminal, ping your router for 10 packets to gather baseline latency.

   **Linux/macOS:**
   ```bash
   ping -c 10 192.168.1.1
   ```

   **Windows:**
   ```powershell
   Test-Connection -TargetName 192.168.1.1 -Count 10
   ```

2. Ping a public endpoint such as `1.1.1.1` and record the minimum, average, and maximum latency.
3. Run a traceroute to `sugarkube.io` to see intermediate hops.

   **Linux/macOS:**
   ```bash
   traceroute sugarkube.io
   ```

   **Windows:**
   ```powershell
   tracert sugarkube.io
   ```

4. Paste the command outputs into your log and annotate any timeouts or unusually high latency.
5. If you have a second device, repeat the ping test from that device and compare results.

> [!WARNING]
> Stop the test if you notice packet loss above 10% or if other household members report degraded
> connectivity. Continuous pings can tax fragile connections.

### 5. Inspect HTTP responses with curl
1. Use `curl` to fetch only the headers from `https://httpbin.org/get`.
   ```bash
   curl -I https://httpbin.org/get
   ```
2. Note the HTTP status code, `Server` header, and the response time reported when using `-w`.
   ```bash
   curl -w '\nTotal time: %{time_total}s\n' -o /dev/null -s https://sugarkube.io
   ```
3. Compare HTTPS and HTTP by running:
   ```bash
   curl -I http://example.com
   ```
   Document how the status codes differ and what that implies about encryption.

### 6. Capture bandwidth measurements
1. If your ISP allows, run the open-source [speedtest-cli](https://www.speedtest.net/apps/cli).
   ```bash
   pip install --user speedtest-cli
   ~/.local/bin/speedtest
   ```
2. Alternatively, open [https://fast.com](https://fast.com) in a browser and wait for the upload
   measurement to complete.
3. Record download speed, upload speed, and latency in your log. Take a screenshot of the results.
4. Note the time of day so you can compare future measurements when diagnosing issues.

> [!QUESTION]
> **Is installing `speedtest-cli` safe?**
>
> The tool is open-source and widely used. If you prefer not to install Python packages globally, run
> it inside a virtual environment: `python3 -m venv ~/.venvs/networking && source ~/.venvs/networking/bin/activate`
> before installing.

### 7. Practice DHCP reservations and firewall rules
1. If you have access to your router, log in and navigate to the DHCP reservation or address
   reservation page. Add a reservation for a test MAC address (for example, `AA-BB-CC-DD-EE-FF`) and
   assign it to an unused IP (for example, `192.168.1.250`). Do **not** assign it to a real device.
2. If you must avoid changes on production equipment, open the
   [TP-Link TL-WR940N simulator](https://emulator.tp-link.com/tl-wr940nv6_eu/index.html#emulator) and
   follow the on-screen instructions to add a reservation under *DHCP > Address Reservation*.
3. Next, add a firewall rule in the emulator (or your router interface) that blocks outgoing TCP
   traffic on port 23 (Telnet). Take a screenshot named `tutorial-03-firewall.png` showing the rule.
4. Document the purpose of each setting in your log. Note how DHCP reservations ensure stable IP
   addresses for devices like Sugarkube nodes.

> [!NOTE]
> Remove any test configuration on your real router after capturing evidence. Leaving unused rules in
> place can cause confusion later.

## Milestone Checklist
Mark each task complete once you have saved proof in the `sugarkube-tutorial-03` folder.

- [ ] **Diagram a home network:** `tutorial-03-network-map.png` exported from diagrams.net with IP
      ranges and connection types labeled.
- [ ] **Run latency and bandwidth measurements:** Ping and traceroute transcripts plus a speed test
      screenshot with timestamps comparing at least two destinations.
- [ ] **Configure a sample firewall or reservation:** Screenshot of the DHCP reservation and port 23
      firewall rule (real router or simulator) with accompanying notes explaining their purpose.

## Troubleshooting
> [!QUESTION]
> **Traceroute shows only asterisks. Is something broken?**
>
> Many routers block ICMP TTL expiry messages. Try `traceroute -I` (Linux/macOS) or `tracert -d`
> (Windows) to force ICMP, or contact your ISP to confirm whether traceroute is filtered.
>
> [!QUESTION]
> **`speedtest-cli` reports permission errors. What can I do?**
>
> Ensure the Python user bin directory is in your `PATH`: `export PATH="$HOME/.local/bin:$PATH"` on
> Linux/macOS or `setx PATH "%USERPROFILE%\AppData\Roaming\Python\Python311\Scripts;%PATH%"` in
> PowerShell. Re-run the command afterward.

## Next Steps
Continue the roadmap by reading [Tutorial 4: Version Control and Collaboration
Fundamentals](./index.md#tutorial-4-version-control-and-collaboration-fundamentals). Bring your
network diagram and latency logs—they will inform how you structure repositories and automation that
monitor Sugarkube nodes.
