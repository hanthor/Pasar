1. Brewfile support

- Support for opening Brewfiles from the file system, bulk install or removal from a list of packages in a Brewfile. launching the app with a Brewfile as an argument should open the Brewfile and display the list of packages.

- support taps? Brewfiles dynamically tapping taps to get info for packages in the brewfile. This would be a nice to have feature.

2. Filter out MacOS-only Casks on Linux

- On Linux, casks that are only available on MacOS should be filtered out from the search results and browse page.

3. Get icons and screenshots for packages

- Get icons and screenshots, this may be difficult and we may need to use a different API or method to get them, maintaining a local cache of icons and screenshots would be ideal. Maybe making out own database in GitHub using ORAS.

4. Recently Added is just reverse alphabetical, not actually recently added