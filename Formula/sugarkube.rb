class Sugarkube < Formula
  desc "Automation helpers and setup wizard for the Sugarkube Pi image"
  homepage "https://github.com/futuroptimist/sugarkube"
  url "https://github.com/futuroptimist/sugarkube.git", branch: "main"
  version "0.0.0-main"
  depends_on "python@3.11"

  def install
    libexec.install "scripts/sugarkube_setup.py"
    (bin/"sugarkube-setup").write <<~SH
      #!/bin/bash
      exec "#{Formula["python@3.11"].opt_bin}/python3" "#{libexec}/sugarkube_setup.py" "$@"
    SH
  end

  test do
    system "#{bin}/sugarkube-setup", "--help"
  end
end
