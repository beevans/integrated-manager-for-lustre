# Vagrantfiles

## Setup IML with Vagrant and VirtualBox

The IML Team typically uses [Vagrant](https://www.vagrantup.com) and [VirtualBox](https://www.virtualbox.org/wiki/Downloads) for day to day development tasks. The following guide will provide an overview of how to setup a development environment from scratch.

1. Clone the [Integrated Manager For Lustre repo](https://github.com/whamcloud/integrated-manager-for-lustre) from Github:

   ```sh
   git clone https://github.com/whamcloud/Vagrantfiles.git
   ```

1. Navigate to the `integrated-manager-for-lustre/vagrant` directory

### MacOS

1. Install Homebrew

   [Homebrew](https://brew.sh/) provides a package manager for macos. We will use this to install dependencies in the following steps. See the [Homebrew](https://brew.sh) website for installation instructions.

1. Install Vagrant and VirtualBox

   Using the `brew cask` command:

   ```sh
   brew cask install vagrant virtualbox
   ```

1. Create the default hostonlyif needed by the cluster:

   ```sh
   VBoxManage hostonlyif create
   ```

1. Bring up the cluster (manager, 2 mds, 2 oss, 2 client nodes)

   ```sh
   vagrant up
   ```

1. You may want the latest packages from upstream repos. If so, run the following provisioner and restart the cluster

   ```sh
   vagrant provision --provision-with=yum-update
   vagrant reload
   ```

1. Install the latest IML from [copr-devel](https://copr.fedorainfracloud.org/coprs/managerforlustre/manager-for-lustre-devel/)

   ```sh
   vagrant provision --provision-with=install-iml-devel
   ```

At this point you should be able to access the IML GUI on your host at https://localhost:8443

From here you can decide what type of setup to run.

- Monitored Ldiskfs:

  ```sh
  vagrant provision --provision-with=install-ldiskfs-no-iml,configure-lustre-network,create-ldiskfs-fs,create-ldiskfs-fs2,mount-ldiskfs-fs,mount-ldiskfs-fs2
  ```

- Monitored ZFS:

  ```sh
  vagrant provision --provision-with=install-zfs-no-iml,configure-lustre-network,create-pools,zfs-params,create-zfs-fs
  ```

- Managed Mode:

  1. ```sh
     vagrant provision --provision-with=deploy-managed-hosts adm
     ```

  1. <https://whamcloud.github.io/Online-Help/docs/Contributor_Docs/cd_Managed_ZFS.html>

- Monitored Ldiskfs with LVM Metadata:

  ```sh
   vagrant provision --provision-with=install-ldiskfs-no-iml,configure-lustre-network,create-ldiskfs-lvm-fs,mount-ldiskfs-lvm-fs
  ```

- Monitored Ldiskfs with LVM Metadata and HA:

  ```sh
   vagrant provision --provision-with=install-ldiskfs-no-iml,configure-lustre-network,create-ldiskfs-lvm-fs,ha-ldiskfs-lvm-fs-prep
   VBOX_PASSWD=<ROOT_PW_HERE>
   vagrant provision --provision-with=ha-ldiskfs-lvm-fs-setup
  ```

### Windows

This is tested on Windows 10 1909.

**Ensure your Windows user home folder doesn't contain non-ASCII chracters.** Common case would be when user name you entered when configuring Windows for first use, was Cyrillic. Windows and apps still don't properly support it, and there are issues with encoding in Ruby, Vagrant and shell scripts in case your home is something like `C:\Users\Михаил`.

1. [Install Chocolatey](https://chocolatey.org/install#individual).
   If it fails with errors suggesting update of .NET Framework, go to Windows Update and get all the latest updates.

1. Install Vagrant and VirtualBox using Chocolatey:

```sh
choco install vagrant
choco upgrade virtualbox --version=6.0.6
```

**Warning**: there's an unresolved bug which causes guest CentOS 7 to kernel panic in VirtualBox 6.0.14 on modern Windows 10. Hence the requirement of VirtualBox 6.0.6.
[Details](https://forums.virtualbox.org/viewtopic.php?f=3&t=94358&sid=121c40fa78668a52835a3ce56b63f389&start=15#p457443).

**Further notes**: VirtualBox Extensions 6.0.6 can't be built for CentOS 7. [Details](https://forums.virtualbox.org/viewtopic.php?f=3&t=94777). It's fixed even further upstream (maybe 6.0.14 or later). This means you won't be able to use CentOS in VirtualBox as a development environment (screen resolution, shared folders and other features don't work). Workaround is to use VMWare Player, which is also available on Chocolatey.

1. Bring up the cluster with

```sh
vagrant up
```

and continue as with MacOS.
