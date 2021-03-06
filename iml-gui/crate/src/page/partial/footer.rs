// Copyright (c) 2020 DDN. All rights reserved.
// Use of this source code is governed by a MIT-style
// license that can be found in the LICENSE file.

use crate::{generated::css_classes::C, Msg};
use chrono::{offset::Local, Datelike};
use seed::{prelude::*, *};

pub fn view() -> impl View<Msg> {
    let year = Local::now().year();

    footer![
        class![C.h_5, C.flex, C.justify_center],
        div![
            class![C.px_5, C.text_sm, C.items_center,],
            "Integrated Manager for Lustre software 6.0.0-1 is Copyright © ",
            &year.to_string(),
            " DDN. All rights reserved.",
        ]
    ]
}
