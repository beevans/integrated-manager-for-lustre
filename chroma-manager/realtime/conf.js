//
// INTEL CONFIDENTIAL
//
// Copyright 2013-2015 Intel Corporation All Rights Reserved.
//
// The source code contained or described herein and all documents related
// to the source code ("Material") are owned by Intel Corporation or its
// suppliers or licensors. Title to the Material remains with Intel Corporation
// or its suppliers and licensors. The Material contains trade secrets and
// proprietary and confidential information of Intel or its suppliers and
// licensors. The Material is protected by worldwide copyright and trade secret
// laws and treaty provisions. No part of the Material may be used, copied,
// reproduced, modified, published, uploaded, posted, transmitted, distributed,
// or disclosed in any way without Intel's prior express written permission.
//
// No license under any patent, copyright, trade secret or other intellectual
// property right is granted to or conferred upon you by disclosure or delivery
// of the Materials, either expressly, by implication, inducement, estoppel or
// otherwise. Any license under such intellectual property rights must be
// express and approved by Intel in writing.


/** @module conf */

'use strict';

var conf = require('./conf.json');
var url = require('url');
var _ = require('lodash-mixins');

var parsedPrimusHttpUrl = url.parse(conf.SERVER_HTTP_URL);
var parsedApiHttpUrl = _.clone(parsedPrimusHttpUrl);

parsedPrimusHttpUrl.port = conf.PRIMUS_PORT;
parsedPrimusHttpUrl.protocol = 'http';
delete parsedPrimusHttpUrl.host;

parsedApiHttpUrl.pathname = '/api/';

module.exports = {
  get isProd() {
    return conf.MODE === 'PROD';
  },
  primusPort: conf.PRIMUS_PORT,
  sourceMapDir: conf.SOURCE_MAP_DIR,
  primusUrl: url.format(parsedPrimusHttpUrl),
  parsedApiUrl: parsedApiHttpUrl,
  apiUrl: url.format(parsedApiHttpUrl),
  mode: conf.MODE
};