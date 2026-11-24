# Homebrew Cask for LocalMinutes (macOS Apple Silicon)
#
# After publishing a GitHub Release, replace `sha256` with the checksum for
# `LocalMinutes-v1.0.0-macOS-arm64.dmg` from the release's `SHA256SUMS.txt`.
#
# Local install:
#   brew install --cask ./packaging/homebrew/localminutes.rb
#
# Tap install:
#   brew tap Andacbasaran/tap
#   brew install --cask localminutes

cask "localminutes" do
  arch arm: "arm64"

  version "1.0.0"
  sha256 "REPLACE_WITH_SHA256_FROM_RELEASE_SHA256SUMS_TXT"

  url "https://github.com/Andacbasaran/LocalMinutes/releases/download/v#{version}/LocalMinutes-v#{version}-macOS-#{arch}.dmg",
      verified: "github.com/Andacbasaran/LocalMinutes/"
  name "LocalMinutes"
  desc "100% offline, bot-free live meeting & lecture transcription, action items, Q&A, and summary studio"
  homepage "https://localminutes.andacbasaran.com"

  livecheck do
    url :url
    strategy :github_latest
  end

  depends_on arch: :arm64
  depends_on macos: ">= :monterey"

  app "LocalMinutes.app"

  caveats <<~EOS
    Microphone capture works out-of-the-box on macOS.
    To also capture remote system meeting audio (Zoom, Meet, Teams) without joining a bot,
    install BlackHole 2ch and create a Multi-Output Device in Audio MIDI Setup:
      brew install blackhole-2ch
  EOS

  zap trash: [
    "~/Library/Application Support/LocalMinutes",
    "~/Library/Preferences/com.andacbasaran.localminutes.plist",
  ]
end
