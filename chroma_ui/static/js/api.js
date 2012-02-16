

/* The Api module wraps the global state used for 
 * accessing the /api/ URL space */
var Api = function() {
  var errored = false;
  var outstanding_requests = 0;
  var api_available = false
  var API_PREFIX = "/api/";
  var UI_ROOT = "/ui/";
  var lost_contact = false;
  var calls_waiting = 0;
  var enable_overlay = true;

  function testMode(enable)
  {
    if (enable == undefined) {
      return !enable_overlay
    }
    if (enable) {
      enable_overlay = false;
      jQuery.fx.off = true;
      $.unblockUI();
    } else {
      enable_overlay = true;
    }

    return "rhubarb"
  }

  var startBlocking = function()
  {
    if (errored) {
      return;
    }

    outstanding_requests += 1;
    if (outstanding_requests == 1 && enable_overlay) {
      $.blockUI({
        message: ""
      });
    }
  }

  var completeBlocking = function()
  {
    if (errored) {
      return;
    }

    outstanding_requests -= 1;
    if (outstanding_requests == 0 && enable_overlay) {
      $.unblockUI();
    }
  }

  var enable = function()
  {
    api_available = true;
    $('body').trigger('api_available');
  }

  function unexpectedError (jqXHR)
  {
      /* Caller has provided no error handlers, this is a bug
         or unhandled error */
      try {
        var response_content = JSON.parse(jqXHR.responseText)
      } catch(e) {
        blockingError({
          Status: jqXHR.status + "(" + jqXHR.statusText + ")",
          'Response headers': jqXHR.getAllResponseHeaders(),
          'Response body': jqXHR.responseText
        });
      }
      if (response_content.error_message && response_content.traceback) {
        // An API exception
        blockingError({
          'Status': jqXHR.status,
          'Exception': response_content.error_message,
          'Backtrace': response_content.traceback
        })
      } else if (jqXHR.status == 400) {
        // A validation error
        validationError(response_content)
      } else {
        blockingError({
          'Status': jqXHR.status + "(" + jqXHR.statusText + ")",
          'Response headers': jqXHR.getAllResponseHeaders(),
          'Response body': response_content
        });
      }
  }

  /* An unknown error which may have left the UI in an
   * inconsistent state: block the UI, disable further
   * API calls until the page is reloaded */
  function blockingError(kwargs)
  {
    errored = true;
    var message = "We are sorry, but something has gone wrong.";
    message += "<dl>";
    $.each(kwargs, function(key, value) {
      var s = String(value);
      if (s.length > 160) {
        s = "<textarea rows='8' cols='40'>" + s + "</textarea>"
      }
      message += "<dt>" + key + ":</dt><dd>" + s + "</dd>";
    });
    message += "</dl>";
    message += "<p style='text-align: center'>"
    message += "<a href='" + UI_ROOT + "'>Reload</a>"
    message += "</p>"

    /* NB: we 'reload' them back to the base URL because a malformed URL is a possible
     * cause of errors (e.g. if the hash had a bad ID in it) */
    $.blockUI({
      message: message,
      css: {padding: "6px", "font-size": "9pt", "text-align": "left"}
    });
  }

  /* A rejected request (400) -- assume that this was
   * a recoverable validation error and provide a generic
   * notification which will not block the UI */
  function validationError(field_errors)
  {
    var list_markup = "<dl>";
    $.each(field_errors, function(field, errors) {
      $.each(errors, function(i, error) {
        list_markup += "<dt>" + field + "</dt><dd>" + error + "</dd>";
      });
    });
    list_markup += "</dl>";

    $("<div><h2>Validation errors</h2>" + list_markup + "</div>").dialog({
        buttons: {
          "Dismiss": function(){$(this).dialog('close');}
        }
    })
  }



  var get = function() {
    call.apply(null, ["GET"].concat([].slice.apply(arguments)))
  }
  var post = function() {
    call.apply(null, ["POST"].concat([].slice.apply(arguments)))
  }
  var put = function() {
    call.apply(null, ["PUT"].concat([].slice.apply(arguments)))
  }
  var del = function() {
    call.apply(null, ["DELETE"].concat([].slice.apply(arguments)))
  }

  /* Wrap API calls to tastypie paginated methods such that
     jquery.Datatables understands the resulting format */
  var get_datatables = function(url, data, callback, settings, kwargs, datatable) {
    var kwargs = kwargs;
    if (kwargs == undefined) {
      kwargs = {}
    }
      
    /* Copy datatables args into our dict */
    if (data) {
      $.each(data, function(i, param) {
        kwargs[param.name] = param.value
      });
    }

    if (!kwargs.order_by && kwargs.iSortCol_0 != undefined) {
      if (kwargs['bSortable_' + kwargs.iSortCol_0]) {
        console.log(settings.aoColumns)
        var order_by = settings.aoColumns[kwargs.iSortCol_0].mDataProp
        if (kwargs.sSortDir_0 == 'desc') {
          kwargs.order_by = "-" + order_by
        } else if (kwargs.sSortDir_0 == 'asc') {
          kwargs.order_by = order_by;
        }
      }
    }

    /* Rename pagination params from datatables to tastypie */
    if (kwargs.iDisplayLength == -1) {
      kwargs.limit = 0
    } else {
      kwargs.limit = kwargs.iDisplayLength
    }
    delete kwargs.iDisplayLength

    kwargs.offset = kwargs.iDisplayStart
    delete kwargs.iDisplayStart

    get(url, kwargs, success_callback = function(data) {
      var datatables_data = {}
      datatables_data.aaData = data.objects;
      datatables_data.iTotalRecords = data.meta.total_count
      datatables_data.iTotalDisplayRecords = data.meta.total_count
      callback(datatables_data);
    }, error_callback = null, blocking = false);
  }

  var lost_contact = false;
  var lost_contact_at;
  var CONTACT_RETRY_INTERVAL = 5000;
  function lostContact ()
  {
    if (lost_contact) {
      return;
    } else {
      lost_contact = true;
      lost_contact_at = Number(Date.now())
      //console.log("Api: Lost contact at " + Date.now());

        var spinner_img = '<img width="16" height="16" title="" alt="" src="data:image/gif;base64,R0lGODlhEAAQAPIAAP///wAAAMLCwkJCQgAAAGJiYoKCgpKSkiH/C05FVFNDQVBFMi4wAwEAAAAh/hpDcmVhdGVkIHdpdGggYWpheGxvYWQuaW5mbwAh+QQJCgAAACwAAAAAEAAQAAADMwi63P4wyklrE2MIOggZnAdOmGYJRbExwroUmcG2LmDEwnHQLVsYOd2mBzkYDAdKa+dIAAAh+QQJCgAAACwAAAAAEAAQAAADNAi63P5OjCEgG4QMu7DmikRxQlFUYDEZIGBMRVsaqHwctXXf7WEYB4Ag1xjihkMZsiUkKhIAIfkECQoAAAAsAAAAABAAEAAAAzYIujIjK8pByJDMlFYvBoVjHA70GU7xSUJhmKtwHPAKzLO9HMaoKwJZ7Rf8AYPDDzKpZBqfvwQAIfkECQoAAAAsAAAAABAAEAAAAzMIumIlK8oyhpHsnFZfhYumCYUhDAQxRIdhHBGqRoKw0R8DYlJd8z0fMDgsGo/IpHI5TAAAIfkECQoAAAAsAAAAABAAEAAAAzIIunInK0rnZBTwGPNMgQwmdsNgXGJUlIWEuR5oWUIpz8pAEAMe6TwfwyYsGo/IpFKSAAAh+QQJCgAAACwAAAAAEAAQAAADMwi6IMKQORfjdOe82p4wGccc4CEuQradylesojEMBgsUc2G7sDX3lQGBMLAJibufbSlKAAAh+QQJCgAAACwAAAAAEAAQAAADMgi63P7wCRHZnFVdmgHu2nFwlWCI3WGc3TSWhUFGxTAUkGCbtgENBMJAEJsxgMLWzpEAACH5BAkKAAAALAAAAAAQABAAAAMyCLrc/jDKSatlQtScKdceCAjDII7HcQ4EMTCpyrCuUBjCYRgHVtqlAiB1YhiCnlsRkAAAOwAAAAAAAAAAAA==" />'
      $.blockUI({
        message: spinner_img + "&nbsp;Contact lost with " + window.location.hostname + ", retrying every " + CONTACT_RETRY_INTERVAL/1000 + " seconds...",
        css: {padding: "6px", "font-size": "9pt"}
      });

      testContact();
    }
  }

  function testContact ()
  {
    $.ajax({type: "GET", url: "/api/session/"}).complete(function(jqXHR) {
      if (jqXHR.status != 0) {
        lost_contact = false;
        $.unblockUI();
        //console.log("Api: Regained contact at " + Number(Date.now()));
        //console.log("Api: Out for " + (Number(Date.now()) - lost_contact_at)/1000 + " seconds");
        $('body').trigger('api_available');
      } else {
        //console.log("Api: Still out of contact at " + Date.now());
        //console.log("Api: " + calls_waiting + " calls waiting");
        //console.log("Api: Out for " + (Number(Date.now()) - lost_contact_at)/1000 + " seconds");
        setTimeout(testContact, CONTACT_RETRY_INTERVAL);
      }
    });
  }

  var call = function(verb, url, api_args, success_callback, error_callback, blocking, force)
  {
    /* Allow user to pass either /filesystem or /api/filesystem */
    if (!(url.indexOf(API_PREFIX) == 0)) {
      url = API_PREFIX + url;
    }

    /* Permanent failures, do nothing */
    if (errored) {
      return;
    }

    /* Default to blocking calls */
    if (blocking == undefined) {
      blocking = true;
    }

    /* If .enable() hasn't been called yet (done after checking
     * user permissions), then defer this call until an event
     * is triggered */
    if ((!force && !api_available) || lost_contact) {
      calls_waiting += 1;
      $('body').bind('api_available', function() {
        calls_waiting -= 1;
        call(verb, url, api_args, success_callback, error_callback, blocking);
      });
      return;
    }

    var ajax_args = {
        type: verb,
        url: url,
        headers: {
          Accept: "application/json"
        }
    };

    if (verb == "GET") {
      ajax_args.data = api_args
    } else {
      ajax_args.dataType = 'json'
      ajax_args.data = JSON.stringify(api_args)
      ajax_args.contentType ="application/json; charset=utf-8"
    }

    if (blocking) {
      startBlocking();
    }

    $.ajax(ajax_args)
    .success(function(data, textStatus, jqXHR)
    {
      if (success_callback) {
        if(typeof(success_callback) == "function") {
          /* If success_callback is a function, call it */
          success_callback(data);
        } else {
          /* If success_callback is not a function, assume it
             is a lookup object of response code to callback */
          var status_code = jqXHR.status;
          if(success_callback[status_code] != undefined) {
            success_callback[status_code](data);
          } else {
            /* Caller gave us a lookup table of success callbacks
               but we got a response code that was successful but
               unhandled -- consider this a bug or error */ 
            unexpectedError(jqXHR);
          }
        }
      }
    })
    .error(function(jqXHR, textStatus)
    {
      //console.log("error " + jqXHR.status);
      if (jqXHR.status == 0) {
        /* This is a workaroud to deal with the fact that some POSTs
         * are actually read-only (especially the /notifications/ and
         * /object_summary).  Remove these training wheels before release.
         * HYD-618
         * */

        var HACK_RETRY_ALL = true
        if (verb == "GET" || verb == "PUT" || verb == "DELETE" || HACK_RETRY_ALL) {
          // For idempotent HTTP verbs, we can retry once
          // contact is reestablished
          lostContact();
          calls_waiting += 1;
          $('body').bind('api_available', function() {
            calls_waiting -= 1;
            call(verb, url, api_args, success_callback, error_callback, blocking)
          });
          return;
        }
        // For non-idempotent operations fall through to 'something has
        // gone wrong' to prompt the user to reload the UI as we can
        // no longer be sure of the state.
      }
      if (error_callback) {
        if(typeof(error_callback) == "function") {
          /* Caller has provided a generic error handler */
          rc = error_callback(jqXHR.responseText);
          if (rc == false) {
            unexpectedError(jqXHR);
          }
        } else if(typeof(error_callback) == "object") {
          var status_code = jqXHR.status;
          if(error_callback[status_code] != undefined) {
            /* Caller has provided handler for this status */
            rc = error_callback[status_code](jqXHR);
            if (rc == false) {
              unexpectedError(jqXHR);
            }
          } else {
            /* Caller has provided some handlers, but not one for this
               status code, this is a bug or unhandled error */
            unexpectedError(jqXHR);
          }
        }
      } else {
        unexpectedError(jqXHR);

      }
    })
    .complete(function(event)
    {
      if (blocking) {
        completeBlocking();
      }
    });
  }

  function busy()
  {
    return (outstanding_requests > 0)
  }

  return {
    enable: enable,
    call : call,
    get: get,
    post: post,
    put: put,
    busy: busy, 
    testMode: testMode,
    'delete': del,
    get_datatables: get_datatables,
  }
}();

/* https://docs.djangoproject.com/en/1.2/ref/contrib/csrf/#csrf-ajax */
$(document).ajaxSend(function(event, xhr, settings) {
    function getCookie(name) {
        var cookieValue = null;
        if (document.cookie && document.cookie != '') {
            var cookies = document.cookie.split(';');
            for (var i = 0; i < cookies.length; i++) {
                var cookie = jQuery.trim(cookies[i]);
                // Does this cookie string begin with the name we want?
                if (cookie.substring(0, name.length + 1) == (name + '=')) {
                    cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                    break;
                }
            }
        }
        return cookieValue;
    }
    function sameOrigin(url) {
        // url could be relative or scheme relative or absolute
        var host = document.location.host; // host + port
        var protocol = document.location.protocol;
        var sr_origin = '//' + host;
        var origin = protocol + sr_origin;
        // Allow absolute or scheme relative URLs to same origin
        return (url == origin || url.slice(0, origin.length + 1) == origin + '/') ||
            (url == sr_origin || url.slice(0, sr_origin.length + 1) == sr_origin + '/') ||
            // or any other URL that isn't scheme relative or absolute i.e relative.
            !(/^(\/\/|http:|https:).*/.test(url));
    }
    function safeMethod(method) {
        return (/^(GET|HEAD|OPTIONS|TRACE)$/.test(method));
    }

    if (!safeMethod(settings.type) && sameOrigin(settings.url)) {
        xhr.setRequestHeader("X-CSRFToken", getCookie('csrftoken'));
    }

});

function removeBlankAttributes(obj) {
  $.each(obj, function(attr_name, attr_val) {
    if (attr_val == "") {
      delete obj[attr_name]
    }
  });
  return obj;
}


/* http://snipplr.com/view/5945/ */
function formatNumber(number, decimals, dec_point, thousands_sep) {
    // http://kevin.vanzonneveld.net
    // +   original by: Jonas Raoni Soares Silva (http://www.jsfromhell.com)
    // +   improved by: Kevin van Zonneveld (http://kevin.vanzonneveld.net)
    // +     bugfix by: Michael White (http://crestidg.com)
    // +     bugfix by: Benjamin Lupton
    // +     bugfix by: Allan Jensen (http://www.winternet.no)
    // +    revised by: Jonas Raoni Soares Silva (http://www.jsfromhell.com)    
    // *     example 1: number_format(1234.5678, 2, '.', '');
    // *     returns 1: 1234.57     
 
    var n = number, c = isNaN(decimals = Math.abs(decimals)) ? 2 : decimals;
    var d = dec_point == undefined ? "," : dec_point;
    var t = thousands_sep == undefined ? "." : thousands_sep, s = n < 0 ? "-" : "";
    var i = parseInt(n = Math.abs(+n || 0).toFixed(c)) + "", j = (j = i.length) > 3 ? j % 3 : 0;
 
    return s + (j ? i.substr(0, j) + t : "") + i.substr(j).replace(/(\d{3})(?=\d)/g, "$1" + t) + (c ? d + Math.abs(n - i).toFixed(c).slice(2) : "");
}

/* http://snipplr.com/view/5949/ */
function formatBytes(bytes) {
  if (bytes == null || bytes == undefined) {
    return bytes;
  }

	if (bytes >= 1073741824) {
	     bytes = formatNumber(bytes / 1073741824, 2, '.', '') + 'GB';
	} else { 
		if (bytes >= 1048576) {
     		bytes = formatNumber(bytes / 1048576, 2, '.', '') + 'MB';
   	} else { 
			if (bytes >= 1024) {
    		bytes = formatNumber(bytes / 1024, 0) + 'KB';
  		} else {
    		bytes = formatNumber(bytes, 0) + 'b';
			};
 		};
	};
  return bytes;
}

function shortLocalTime(str)
{
  function pad(n) {
    if (n < 10) {
      return "0" + n
    } else {
      return n
    }
  }
  var date = new Date(str)
  var days_elapsed = ((new Date()) - date) / (3600 * 24 * 1000)
  var localTime = pad(date.getHours()) + ":" + pad(date.getMinutes())
  var localDate = date.getFullYear() + "/" + pad(date.getMonth()) + "/" + pad(date.getDate())
  if (days_elapsed < 1.0) {
    return localTime
  } else {
    return  localDate + "&nbsp;" + localTime
  }
}


