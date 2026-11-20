class Rbk < Formula
  desc "Lightweight, Git-native CLI runbook runner over plain OpenSSH"
  homepage "https://github.com/J-Schiemer/rbk"
  # url and sha256 are rendered by .github/workflows/release.yml into the
  # J-Schiemer/homebrew-tap repository on every v* tag; the values here are
  # the local template and are never published as-is.
  url "https://github.com/J-Schiemer/rbk/archive/refs/tags/v0.1.0.tar.gz"
  sha256 "0000000000000000000000000000000000000000000000000000000000000000"
  license "MIT"
  head "https://github.com/J-Schiemer/rbk.git", branch: "main"

  depends_on "python@3.12"
  depends_on "uv"

  def install
    ENV["UV_TOOL_DIR"] = libexec/"uv-tools"
    ENV["UV_TOOL_BIN_DIR"] = libexec/"bin"

    system "uv", "tool", "install",
           "--python", formula_opt_bin("python@3.12")/"python3.12",
           "--force", "."

    bin.install_symlink libexec/"bin/rbk"
  end

  test do
    assert_match version.to_s, shell_output("#{bin}/rbk --version")
  end
end
