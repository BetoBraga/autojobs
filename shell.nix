{ pkgs ? import <nixpkgs> {} }:

pkgs.mkShell {
  packages = with pkgs; [
    gcc
    chromium
    chromedriver
    python313
    python313Packages.pip
  ];

  shellHook = ''
    export PATH=$PATH:${pkgs.chromedriver}/bin:${pkgs.chromium}/bin
    export CHROME_BIN=${pkgs.chromium}/bin/chromium
    export CHROMEDRIVER_PATH=${pkgs.chromedriver}/bin/chromedriver
    echo "autojobs development shell"
  '';
}
