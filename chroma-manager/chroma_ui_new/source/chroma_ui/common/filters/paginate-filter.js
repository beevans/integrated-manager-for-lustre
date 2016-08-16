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


angular.module('filters').filter('paginate', [function paginate () {
  'use strict';

  /**
   * The pagination filter, which returns the entries according to the page the guest is viewing and the number of
   * items that can be displayed on that page.
   * @param {Array} input
   * @param {Number} currentPage
   * @param {Number} itemsPerPage
   * @returns {Array}
   */
  return function paginateFilter(input, currentPage, itemsPerPage) {
    var startingItem = itemsPerPage * currentPage;
    var endingItem = startingItem + itemsPerPage - 1;

    return input.filter(showValidItems(startingItem, endingItem));
  };

  /**
   * Returns a function that is used for filtering only the items that should be displayed on the current page.
   * @param {Number} startingItem
   * @param {Number} endingItem
   * @returns {Function}
   */
  function showValidItems (startingItem, endingItem) {
    /**
     * Computes whether or not the current item should be displayed.
     * @param {*} val
     * @param {Number} index
     */
    return function innerShowValidItems (val, index) {
      return index >= startingItem && index <= endingItem;
    };
  }
}]);

