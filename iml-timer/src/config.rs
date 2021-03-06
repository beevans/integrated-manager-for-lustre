// Copyright (c) 2020 DDN. All rights reserved.
// Use of this source code is governed by a MIT-style
// license that can be found in the LICENSE file.

use crate::error::TimerError;
use futures::TryFutureExt;
use serde::{Deserialize, Serialize};
use tokio::{
    fs::{remove_file, File},
    prelude::*,
};

#[derive(Deserialize, Serialize)]
pub struct ConfigDetails {
    config_id: String,
    timer_config: String,
    service_config: String,
}

#[derive(Deserialize, Serialize)]
pub struct DeleteConfigDetails {
    config_id: String,
}

pub struct ConfigFile {
    pub name: String,
    pub content: String,
}

pub struct ConfigFiles {
    pub timer_file: ConfigFile,
    pub service_file: ConfigFile,
}

pub fn unit_name(fid: &str) -> String {
    format!("iml-stratagem-{}", fid)
}

pub fn timer_file(fid: &str) -> String {
    format!("/etc/systemd/system/{}.timer", unit_name(fid))
}

pub fn service_file(fid: &str) -> String {
    format!("/etc/systemd/system/{}.service", unit_name(fid))
}

pub fn get_config(config: ConfigDetails) -> (String, ConfigFiles) {
    (
        config.config_id.clone(),
        ConfigFiles {
            timer_file: ConfigFile {
                name: timer_file(config.config_id.as_str()),
                content: config.timer_config,
            },
            service_file: ConfigFile {
                name: service_file(config.config_id.as_str()),
                content: config.service_config,
            },
        },
    )
}

pub async fn write_config_to_file(buf: &[u8], file: &str) -> tokio::io::Result<()> {
    let mut file = File::create(file).await?;
    file.write_all(buf).await?;
    Ok(())
}

pub async fn write_config_files(configs: ConfigFiles) -> tokio::io::Result<()> {
    write_config_to_file(
        configs.timer_file.content.as_bytes(),
        &configs.timer_file.name,
    )
    .await?;

    write_config_to_file(
        configs.service_file.content.as_bytes(),
        &configs.service_file.name,
    )
    .await?;

    Ok(())
}

pub async fn write_configs(
    (config_id, configs): (String, ConfigFiles),
) -> Result<String, warp::Rejection> {
    write_config_files(configs)
        .map_err(TimerError::IoError)
        .map_err(warp::reject::custom)
        .await?;

    Ok(config_id)
}

pub async fn delete_config(config: &str, config_id: String) -> Result<String, warp::Rejection> {
    remove_file(config)
        .map_err(TimerError::IoError)
        .map_err(warp::reject::custom)
        .await?;

    Ok(config_id)
}
