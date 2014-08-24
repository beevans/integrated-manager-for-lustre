//
// INTEL CONFIDENTIAL
//
// Copyright 2013-2014 Intel Corporation All Rights Reserved.
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


'use strict';

exports.wiretree = function rebuildDepsThenModule (Promise, childProcess, console) {
  /**
   * Rebuilds npm dependencies.
   */
  return function rebuildDepsThen () {
    return new Promise (function handler (resolve, reject) {
      var errors = [];

      var rebuild = childProcess.spawn('npm', ['rebuild']);
      rebuild.stdout.on('data', function logStdOut (data) {
        console.log(data + '');
      });

      rebuild.stderr.on('data', function saveError (data) {
        errors.push(data + '');
      });

      rebuild.on('close', function (code) {
        if (code === 0)
          return resolve(code);

        errors.push('child process exited with code ' + code);

        reject(new Error(errors.join('\n')));
      });
    });
  };
};
