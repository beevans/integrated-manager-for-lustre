// Copyright (c) 2020 DDN. All rights reserved.
// Use of this source code is governed by a MIT-style
// license that can be found in the LICENSE file.

use device_types::devices::{
    Device, LogicalVolume, MdRaid, Mpath, Partition, Root, ScsiDevice, VolumeGroup, Zpool,
};
use diesel::{self, pg::upsert::excluded, prelude::*};
use im::HashSet;

use iml_orm::{
    models::{ChromaCoreDevice, NewChromaCoreDevice},
    schema::chroma_core_device::{self, fqdn, table},
    tokio_diesel::*,
    DbPool,
};

use iml_wire_types::Fqdn;

pub async fn save_devices(devices: Vec<(Fqdn, Device)>, pool: &DbPool) {
    for (f, d) in devices.into_iter() {
        let device_to_insert = NewChromaCoreDevice {
            fqdn: f.to_string(),
            devices: serde_json::to_value(d).expect("Could not convert other Device to JSON."),
        };

        let new_device = diesel::insert_into(table)
            .values(device_to_insert)
            .on_conflict(fqdn)
            .do_update()
            .set(chroma_core_device::devices.eq(excluded(chroma_core_device::devices)))
            .get_result_async::<ChromaCoreDevice>(pool)
            .await
            .expect("Error saving new device");

        tracing::info!("Inserted other device from host {}", new_device.fqdn);
        tracing::trace!("Inserted other device {:?}", new_device);
    }
}

pub async fn get_other_devices(f: &Fqdn, pool: &DbPool) -> Vec<(Fqdn, Device)> {
    let other_devices = table
        .filter(fqdn.ne(f.to_string()))
        .load_async::<ChromaCoreDevice>(&pool)
        .await
        .expect("Error getting devices from other hosts");

    other_devices
        .into_iter()
        .map(|d| {
            (
                Fqdn(d.fqdn),
                serde_json::from_value(d.devices)
                    .expect("Couldn't deserialize Device from JSON when reading from DB"),
            )
        })
        .collect()
}

pub async fn update_virtual_devices(devices: Vec<(Fqdn, Device)>) -> Vec<(Fqdn, Device)> {
    let mut results = vec![];
    let mut parents = vec![];
    let devices2 = devices.clone();

    for (f, d) in devices {
        parents.extend(collect_virtual_device_parents(&d, 0, None));

        tracing::info!(
            "Collected {} parents at {} host",
            parents.len(),
            f.to_string()
        );
    }

    // TODO: Assert that all parents are distinct
    for (ff, mut dd) in devices2 {
        insert_virtual_devices(&mut dd, &*parents);

        results.push((ff, dd));
    }

    results
}

fn is_virtual(d: &Device) -> bool {
    match d {
        Device::Dataset(_)
        | Device::LogicalVolume(_)
        | Device::MdRaid(_)
        | Device::VolumeGroup(_)
        | Device::Zpool(_) => true,
        _ => false,
    }
}

fn to_display(d: &Device) -> String {
    match d {
        Device::Root(d) => format!("Root: children: {}", d.children.len()),
        Device::ScsiDevice(ref d) => format!(
            "ScsiDevice: serial: {}, children: {}",
            d.serial.as_ref().unwrap_or(&"None".into()),
            d.children.len()
        ),
        Device::Partition(d) => format!(
            "Partition: serial: {}, children: {}",
            d.serial.as_ref().unwrap_or(&"None".into()),
            d.children.len()
        ),
        Device::MdRaid(d) => format!("MdRaid: uuid: {}, children: {}", d.uuid, d.children.len()),
        Device::Mpath(d) => format!(
            "Mpath: serial: {}, children: {}",
            d.serial.as_ref().unwrap_or(&"None".into()),
            d.children.len(),
        ),
        Device::VolumeGroup(d) => format!(
            "VolumeGroup: name: {}, children: {}",
            d.name,
            d.children.len()
        ),
        Device::LogicalVolume(d) => format!(
            "LogicalVolume: uuid: {}, children: {}",
            d.uuid,
            d.children.len()
        ),
        Device::Zpool(d) => format!("Zpool: guid: {}, children: {}", d.guid, d.children.len()),
        Device::Dataset(d) => format!("Dataset: guid: {}, children: 0", d.guid),
    }
}

fn collect_virtual_device_parents<'d, 'p: 'd>(
    d: &'d Device,
    level: usize,
    parent: Option<&'p Device>,
) -> Vec<Device> {
    let mut results = vec![];

    if is_virtual(d) {
        tracing::info!(
            "Collecting parent {} of {}",
            parent.map(|x| to_display(x)).unwrap_or("None".into()),
            to_display(d)
        );
        vec![parent
            .expect("Tried to push to parents the parent of the Root, which doesn't exist")
            .clone()]
    } else {
        match d {
            Device::Root(dd) => {
                for c in dd.children.iter() {
                    results.extend(collect_virtual_device_parents(c, level + 1, Some(d)));
                }
                results
            }
            Device::ScsiDevice(dd) => {
                for c in dd.children.iter() {
                    results.extend(collect_virtual_device_parents(c, level + 1, Some(d)));
                }
                results
            }
            Device::Partition(dd) => {
                for c in dd.children.iter() {
                    results.extend(collect_virtual_device_parents(c, level + 1, Some(d)));
                }
                results
            }
            Device::Mpath(dd) => {
                for c in dd.children.iter() {
                    results.extend(collect_virtual_device_parents(c, level + 1, Some(d)));
                }
                results
            }
            _ => vec![],
        }
    }
}

fn _walk(d: &Device) {
    match d {
        Device::Root(d) => {
            for c in &d.children {
                _walk(c);
            }
        }
        Device::ScsiDevice(d) => {
            for c in &d.children {
                _walk(c);
            }
        }
        Device::Partition(d) => {
            for c in &d.children {
                _walk(c);
            }
        }
        Device::MdRaid(d) => {
            for c in &d.children {
                _walk(c);
            }
        }
        Device::Mpath(d) => {
            for c in &d.children {
                _walk(c);
            }
        }
        Device::VolumeGroup(d) => {
            for c in &d.children {
                _walk(c);
            }
        }
        Device::LogicalVolume(d) => {
            for c in &d.children {
                _walk(c);
            }
        }
        Device::Zpool(d) => {
            for c in &d.children {
                _walk(c);
            }
        }
        Device::Dataset(_) => {}
    }
}

fn insert<'a>(d: &'a mut Device, to_insert: &'a Device) {
    if compare_without_children(d, to_insert) {
        tracing::info!(
            "Inserting a device {} to {}",
            to_display(to_insert),
            to_display(d)
        );
        *d = to_insert.clone();
    } else {
        match d {
            Device::Root(d) => {
                for mut c in d.children.iter_mut() {
                    insert(&mut c, to_insert);
                }
            }
            Device::ScsiDevice(d) => {
                for mut c in d.children.iter_mut() {
                    insert(&mut c, to_insert);
                }
            }
            Device::Partition(d) => {
                for mut c in d.children.iter_mut() {
                    insert(&mut c, to_insert);
                }
            }
            Device::MdRaid(d) => {
                for mut c in d.children.iter_mut() {
                    insert(&mut c, to_insert);
                }
            }
            Device::Mpath(d) => {
                for mut c in d.children.iter_mut() {
                    insert(&mut c, to_insert);
                }
            }
            Device::VolumeGroup(d) => {
                for mut c in d.children.iter_mut() {
                    insert(&mut c, to_insert);
                }
            }
            Device::LogicalVolume(d) => {
                for mut c in d.children.iter_mut() {
                    insert(&mut c, to_insert);
                }
            }
            Device::Zpool(d) => {
                for mut c in d.children.iter_mut() {
                    insert(&mut c, to_insert);
                }
            }
            Device::Dataset(_) => {}
        }
    }
}

fn without_children(d: &Device) -> Device {
    match d {
        Device::Root(d) => Device::Root(Root {
            children: HashSet::new(),
            ..d.clone()
        }),
        Device::ScsiDevice(d) => Device::ScsiDevice(ScsiDevice {
            children: HashSet::new(),
            ..d.clone()
        }),
        Device::Partition(d) => Device::Partition(Partition {
            children: HashSet::new(),
            ..d.clone()
        }),
        Device::MdRaid(d) => Device::MdRaid(MdRaid {
            children: HashSet::new(),
            ..d.clone()
        }),
        Device::Mpath(d) => Device::Mpath(Mpath {
            children: HashSet::new(),
            ..d.clone()
        }),
        Device::VolumeGroup(d) => Device::VolumeGroup(VolumeGroup {
            children: HashSet::new(),
            ..d.clone()
        }),
        Device::LogicalVolume(d) => Device::LogicalVolume(LogicalVolume {
            children: HashSet::new(),
            ..d.clone()
        }),
        Device::Zpool(d) => Device::Zpool(Zpool {
            children: HashSet::new(),
            ..d.clone()
        }),
        Device::Dataset(d) => Device::Dataset(d.clone()),
    }
}

fn compare_without_children(a: &Device, b: &Device) -> bool {
    without_children(a) == without_children(b)
}

fn insert_virtual_devices(d: &mut Device, parents: &[Device]) {
    for p in parents {
        insert(d, &p);
    }
}