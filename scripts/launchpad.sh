#!/bin/bash
# Create and upload launchpad package

# parameters: [UPLOAD="yes"] [DIST="<dist>"] [PPA="keyman"]  [PACKAGEVERSION="<version>"] ./scripts/launchpad.sh
# UPLOAD="yes"  do the dput for real. Default: no.
# DIST="<dist>" only upload for this distribution. Multiple distros are possible,
#               separated by space. Default: "bionic focal groovy"
# PPA="keyman"  PPA under keymanapp to upload to. Default: keyman-daily.
# PACKAGEVERSION="<version>" string to append to the package version. Default: 0

set -e

if [ "${UPLOAD}" == "yes" ]; then
    SIM=""
else
    SIM="-s"
fi

if [ "${DIST}" != "" ]; then
    distributions="${DIST}"
else
    distributions="bionic focal groovy"
fi

if [ "${PPA}" != "" ]; then
    ppa="ppa:keymanapp/$PPA"
else
    ppa="ppa:keymanapp/keyman-daily"
fi

if [ "${PACKAGEVERSION}" != "" ]; then
    packageversion="${PACKAGEVERSION}"
else
    packageversion="0"
fi

if [ ! -d .git ]; then
    echo "$0 must to be run from the root of the onboard-keyman tree"
    exit 1
fi

cd ..
version=$(dpkg-parsechangelog -l onboard-keyman/debian/changelog --show-field=Version)
onboard_version=$(dpkg-parsechangelog -l onboard-keyman/debian/changelog --show-field=Version | cut -d '-' -f 1)
echo "Base version: $onboard_version, package version: $version"
rm -rf onboard-keyman-${onboard_version}
rm -rf onboard-keyman_*
cp -a onboard-keyman onboard-keyman-${onboard_version}
rm -rf onboard-keyman-${onboard_version}/debian
rm -rf onboard-keyman-${onboard_version}/.git
tar -czf onboard-keyman_${onboard_version}.orig.tar.gz onboard-keyman-${onboard_version}

cp -a onboard-keyman/debian onboard-keyman-${onboard_version}/

cd onboard-keyman-${onboard_version}

for dist in ${distributions}; do
	echo "Make source packages for ${dist}"
	cp ../onboard-keyman/debian/changelog debian/changelog
	dch -v ${version}.${packageversion}~${dist} "source package for PPA"
	dch -D ${dist} -r ""
	debuild -d -S -sa -Zxz
done
cd ..
for dist in ${distributions}; do
	dput ${SIM} ${ppa} onboard-keyman_${version}.${packageversion}~${dist}_source.changes
done
