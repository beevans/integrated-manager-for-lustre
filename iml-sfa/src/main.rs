// Copyright (c) 2020 DDN. All rights reserved.
// Use of this source code is governed by a MIT-style
// license that can be found in the LICENSE file.

use iml_tracing::tracing;
use std::{collections::BTreeMap, convert::TryInto as _, iter::FromIterator, time::Duration};
use thiserror::Error;
use tokio::time;
use wbem_client::{
    resp::Cim,
    sfa_classes::{SfaClassError, SfaEnclosure},
    ClientExt as _, ResponseExt as _,
};

#[derive(Error, Debug)]
enum ImlSfaError {
    #[error(transparent)]
    WbemClientError(#[from] wbem_client::WbemClientError),
    #[error(transparent)]
    SfaClassError(#[from] SfaClassError),
}

#[tokio::main]
async fn main() -> Result<(), ImlSfaError> {
    iml_tracing::init();

    Ok(())
}
