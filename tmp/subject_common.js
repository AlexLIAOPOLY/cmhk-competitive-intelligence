/* last modified 20251028 */
var classname_for_hideitems = 'canHide';
var product_code ;
var element_list_arr= [];
var cnsd_pub_lang;
var subject_code ;
var press_release_data_dir ; // for getting the subject  master 
var subject_data_dir ;
var statreport_data_dir ;
var whatsnew_data_path;
var data_file_path;
var current_attachment_path;
var en_attachment_path;
var tc_attachment_path;
var sc_attachment_path;
var glossary_data_dir;
var conceptmethod_data_path;
var excel_icon_path = "../iconset/download_xls.svg";
var csv_icon_path  =  "../iconset/download_csv.svg";
var pdf_icon_path  =  "../iconset/download_pdf.svg";
var zip_icon_path  =  "../iconset/download_zip.svg";
var xml_icon_path  =  "../iconset/download_xml.svg";
var more_icon_path  =  "../iconset/download_more.svg";
var tabledownload_icon_path  =  "../iconset/table_download_on.svg"; 
var subject_header_selector = '#w_content';
var subject_path_seperator = '<img src="../icon_set/breadcrumb_next.png">';
var subject_path = {
    selector : ".browse_by_subject>span",
    prefix : function () {
        return (cnsd_pub_lang == "tc") ? "香港統計資料 " +  subject_path_seperator + " 按統計主題瀏覽 " + subject_path_seperator :
               (cnsd_pub_lang == "sc") ? "香港统计资料 " +  subject_path_seperator + " 按统计主题浏览 " + subject_path_seperator : 
               " Statistics " +  subject_path_seperator + " Browse by Subject " + subject_path_seperator;
         }
 };
var month_names = 
{
	"en" : [ "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
	"tc" : ["1月", "2月", "3月", "4月", "5月", "6月", "7月", "8月", "9月", "10月", "11月", "12月"],
	"sc" : ["1月", "2月", "3月", "4月", "5月", "6月", "7月", "8月", "9月", "10月", "11月", "12月"]
};
// 🔹 Mapping of old subject codes to new ones
var subjectCodeMap = {
	"460": "430",
	"461": "390"
};

var month_names_long_en = [ "January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
"use strict";
function makePubTableResponsive(sourceSelector,hideFirstColHeader) {
	var selector = '#'+sourceSelector + " table";
	if (typeof hideFirstColHeader === 'undefined') {
		hideFirstColHeader = true; 
	}
	$(selector).each(function() {
		var parent = this.parentNode;
		var irow = 0;
		var newTable = document.createElement('table');
		newTable.classList.add('publication_table');
		newTable.classList.add('mobile-container');
		$.when(getPubTableColHeaders($(this))).done(function(ch,objthis) {
			if (ch.length > 0) { 
				firstColHeaderobj = ch;
				//for each row        
				objthis.find('tbody tr').each(function() {
					irow++;
					if ($(this).parent().hasClass('footer_note_table') == false) {                         
						$.when(getPubTableDetail($(this),ch)).done(function(cd,ch_inner,objthisInner) {	//get each row in table body detail
							//create one row of mobile table
							var icol = 0;
							$(cd).each(function() {
								var objTR = document.createElement('tr');
								var objTH = document.createElement('th');
								if (typeof ch_inner[icol]['element'][0] === 'undefined')
									var headingInfo = document.createTextNode('');
								else
									var headingInfo  = ch_inner[icol]['element'][0].cloneNode(true);                     
								if (typeof this.element[0] === 'undefined')
									var contentInfo  = document.createTextNode('');
								else
									var contentInfo  = this.element[0].cloneNode(true);
								objTH.appendChild(headingInfo);
								var objTD = document.createElement('td');
								if (this.id != '') {
									$(objTD).attr('id',this.id); 
								}
								if (hideFirstColHeader == true && icol == 0) {
									$(objTD).attr('colspan','2'); 
								} else {
									objTR.appendChild(objTH);
								}
								objTD.appendChild(contentInfo);
								//--added back show hide button 's click event listener
								$(objTD).find("button").each(function() {
									this.addEventListener("click", function() {
										cnsd_publication_genShowMore('cnsd_morelessBtn',classname_for_hideitems);
									});
								});
								objTR.appendChild(objTD);
								$(objTR).attr('class',this.classes);
								newTable.appendChild(objTR);
								icol++;
							});
						});
					}
				});
			}
		});
		parent.appendChild(newTable);
		this.classList.add('big-screen');
	});
}

function getPubTableDetail(objHTML,ch) {
	var deferred = $.Deferred();
	var arrGridElements = [];      
    var iDetailColCount = 0;
	$.when(objHTML.find('td').each(function() {
		iDetailColCount = iDetailColCount + 1 ;
		var objcolDetailClassName = 'col-detail-' + iDetailColCount; 
		var clonedNode = this.cloneNode(true);
		var classes = $(this).parent().attr('class');
		var id = '';
		if (typeof $(this).attr('id') !=='undefined') {
			id = $(this).attr('id');
		}
		classes = classes.replace('row', '');
		classes = classes.replace('g-0', '');
		clonedNode =  $(clonedNode).contents();
		arrGridElements.push({'classname':objcolDetailClassName,'element':clonedNode,'classes':classes,'id':id});              
	})).then(function() {
		deferred.resolve(arrGridElements,ch,objHTML);
	});
	return deferred.promise();  
}

function getPubTableColHeaders(objHTML) {
	var deferred = $.Deferred();
	var iColCount = 0;
	var arrColHeaders = [];  
	$.when(objHTML.find('thead th').each(function() {
		iColCount = iColCount + 1; 
        //add class to hide 2nd and 3rd col header when mobile  
        //store 2nd and 3rd col header caption 
		var objcolHeaderClassName = 'col-header-' + iColCount;      
		var clonedNode = this.cloneNode(true);      
		//--we want only child node --
		if ($(clonedNode).contents().length > 0) {
			//allow for empty string column headers 
			clonedNode = $(clonedNode).contents();
			$(clonedNode).find("[id]").each(function() {    
				this.removeAttribute('id');
			});
			$(clonedNode).find('br').replaceWith('&nbsp;');
			arrColHeaders.push({
				'classname': objcolHeaderClassName,
				'element': clonedNode 
			});
		} else {
			arrColHeaders.push({
				'classname': objcolHeaderClassName, 
				'element': document.createTextNode('')
			});
		}
		this.classList.add('big-screen');
	})).then(function() {
		deferred.resolve(arrColHeaders,objHTML);
    }).fail(function() {      
		deferred.resolve(false,objHTML);
    });
	return deferred.promise();
}

function htmlAddParent(objElement,newParent){
	// `element` is the element you want to wrap
	var parent = objElement.parentNode;
	// set the wrapper as child (instead of the element)
	parent.replaceChild(newParent, objElement);
	// set element as child of wrapper
	newParent.appendChild(objElement);	
}

function close_section(sectionid){
	var sectionname = '#' + sectionid;
	if ($(sectionname).hasClass('show') == true) {
		$(sectionname).toggleClass('show');
		$("a[href='" + sectionname + "']").toggleClass("collapsed");
	}	
}

/* function open_section(sectionid,callback){
	var sectionname = '#' + sectionid;
	if ($(sectionname).hasClass('show') == false) {
		$(sectionname).toggleClass('show');
		$("a[href='" + sectionname + "']").toggleClass("collapsed");
	}	
	if (typeof callback !== 'undefined') {
		callback();
	}
} */
function open_section(sectionid, callback) {
    var section = document.getElementById(sectionid);
    if (!section) return;

    var collapse = new bootstrap.Collapse(section, {
        toggle: false // prevent auto toggle on init
    });

    // Show the section if not already visible
    if (!section.classList.contains('show')) {
        collapse.show();
    }

    if (typeof callback === 'function') {
        callback();
    }
}
/* function open_section(sectionid, callback) {
  var section = document.getElementById(sectionid);
  if (!section) return;

  var collapse = new bootstrap.Collapse(section, {
    toggle: false // prevent auto toggle on init
  });

  // Show the section if not already visible
  if (!section.classList.contains('show')) {
    collapse.show();

    // Find the nearest parent "section" wrapper
    let parent = section.closest("div[id$='_section']"); 
    // e.g. reports_section, income_section, etc.

    if (!parent) {
      // fallback: use the immediate parent node
      parent = section.parentElement;
    }

    if (parent) {
      parent.scrollIntoView({ behavior: "smooth", block: "start" });
      // optional: also move keyboard focus to the toggle link
      const toggle = parent.querySelector("[data-bs-target='#" + sectionid + "']");
      if (toggle) toggle.focus();
    }
  }

  if (typeof callback === 'function') {
    callback();
  }
}
 */


function scrollToSection(section) {
	   
	
	if (parseInt($(section).offset().top) == 0) {
		var ele = document.getElementById(section.replace('#',''));
		$('html, body').animate({
			scrollTop: parseInt(ele.getBoundingClientRect().top) -10 
		});	
	} else {
		$('html, body').animate({
			scrollTop: parseInt($(section).offset().top) -10
		});
	}
}

 function scrollToSection_new(section) {
	var sectionid = section.replace('#','');
	 // Find the toggle button that controls this section
    var $toggle = $("[data-bs-target='#" + sectionid + "']");	   
	// Walk up to its parent's parent's parent
    var $scrollTarget = $toggle.parent().parent();
	 if ($scrollTarget.length) {
     // $scrollTarget[0].scrollIntoView({ behavior: "smooth", block: "start" });
	   $('html, body').animate(
  		{ scrollTop: $scrollTarget.offset().top },0 );
    }
	else
	{
			if (parseInt($(section).offset().top) == 0) {
				var ele = document.getElementById(section.replace('#',''));
				$('html, body').animate({
					scrollTop: parseInt(ele.getBoundingClientRect().top) -10 
				},0);	
			} else {
				$('html, body').animate({
					scrollTop: parseInt($(section).offset().top) -10
				},0);
			}
		
		
	}

    // Accessibility: update aria-expanded and focus the toggle
    if ($toggle.length) {
      $toggle.attr("aria-expanded", "true").focus();
    }
	
} 

function is_Numeric(num) {
  return !isNaN(parseFloat(num)) && isFinite(num);
}

function convertELtoArray(para_pcode) {
	var deferred = $.Deferred();
	if (is_Numeric(para_pcode)) {
		deferred.resolve(false);
		return deferred.promise();
	}
	var element_list1 =[];
	var att1 =[];
	var today = new Date();
	var pcode = '';
	if (para_pcode != null) {
		pcode = para_pcode;
	} else {
		pcode = product_code; 
	}
	var rootPath = "/" + cnsd_pub_lang + "/data/stat_report/product/" + pcode ;  
	var indexPath  = "/en/data/stat_report/product/" + pcode + "/report_element_index.json";
    $.getJSON(getCacheFile(indexPath), function(data){
		var arrList = data.elementindex;
		var tasks = []; 
		//added by dicky 20210126
		if (arrList.length == 0) {			
			deferred.resolve(false);
			return deferred.promise();
		}		
		var buildElementPromises = function (arrList) {
			var element_res = [];
			for (i = 0; i < arrList.length; i++) {
				var p = new Promise(function (resolve, reject) {
					// this is called immediately and it starts
					// an asynchronous operation that will finish later					
					var task = $.getJSON(getCacheFile(rootPath  + '/report_element_' + arrList[i] + '.json'), function(data, status, xhr) {
						var exp_date = getExpDate(data);
						if (exp_date > today) {	//only filter no expired elements
							element_list1.push(data.elementlist[0]);
							if (typeof data.att !== 'undefined') {
								for (var x = 0; x < data.att.length; x++) {
									att1.push(data.att[x]);
								}
							}
						}
						resolve();
						}).fail(function() { 
							resolve();
						}).done(function() {
					});
				});
				element_res.push(p);
			}
			return Promise.all(element_res);
		}
		buildElementPromises(arrList).then(function (results) {
			if (element_list1.length > 0) {
				deferred.resolve({
					'elementlist': element_list1,
					'att': att1
				});
			} else {
				deferred.resolve(false);
			}
		});
	});  
    return deferred.promise();
}

function readOneElementFile_productpage(rootPath,arrElementIndex,curIndex,newElementList,new_att) {      
  var deferred = $.Deferred();
  var today = new Date();
  var e_path =  rootPath  + '/report_element_' + arrElementIndex[curIndex] + '.json';
  $.getJSON(getCacheFile(e_path), function(data) {
		var exp_date = getExpDate(data);
		if (exp_date > today) {	//only filter  no expired elements
			newElementList.push(data.elementlist[0]);
			if (typeof data.att !== 'undefined') {
				for (var x = 0; x < data.att.length; x++) {
					new_att.push(data.att[x]);
				}
			}
			//trivial case then resolve real array list 
			if (curIndex == arrElementIndex.length - 1) {	// if already EOF
				deferred.resolve({
					'elementlist': newElementList,
					'att': new_att
				}); 
			} else {	// continue find next element
				deferred.resolve(readOneElementFile_productpage(rootPath,arrElementIndex,curIndex+1,newElementList,new_att));
			}
		} else {	// expired 
			if (curIndex == arrElementIndex.length - 1) {     // if already EOF
				deferred.resolve({
					'elementlist': newElementList,
					'att': new_att
				});
			} else {	// continue find next element
				deferred.resolve(readOneElementFile_productpage(rootPath,arrElementIndex,curIndex+1,newElementList,new_att));
			}
		}
	}).fail(function() { 
        if (curIndex == arrElementIndex.length - 1) {
			console.log('fail and last element for json path:' + e_path);
			deferred.resolve(false);
        } else {
			console.log('continue to find next element for json path:' + e_path);
			deferred.resolve(readOneElementFile_productpage(rootPath,arrElementIndex,curIndex+1,newElementList,new_att));
        }
   });
   return deferred.promise();
}

function readOneElementFile(rootPath,arrElementIndex,curIndex) {      
	var deferred = $.Deferred();
	var today = new Date();
	var e_path = rootPath  + '/report_element_' + arrElementIndex[curIndex] + '.json';
	var element_list = [];
	var att = [];  
    $.getJSON(getCacheFile(e_path), function(data) {
		var exp_date = getExpDate(data);      
        if (exp_date > today) {	//only filter  no expired elements
			element_list.push(data.elementlist[0]);            
            if (typeof data.att !== 'undefined') {
                for (var x = 0; x < data.att.length; x++) {
                    att.push(data.att[x]);
                }
            }
            deferred.resolve({
				'elementlist': element_list,
				'att': att
			});
		} else {	// expired 
			if (curIndex == arrElementIndex.length - 1) {     // if already EOF
				deferred.resolve(false);
            } else {	// continue find next element
                deferred.resolve(readOneElementFile(rootPath,arrElementIndex,curIndex+1));                
            }
		}
    }).fail(function() { 
		if (curIndex == arrElementIndex.length - 1) {
			console.log('fail and last element for json path:' + e_path);
			deferred.resolve(false);
        } else {
          console.log('continue to find next element for json path:' + e_path);
          deferred.resolve(readOneElementFile(rootPath,arrElementIndex,curIndex+1));
        }
	});
	return deferred.promise();
}

function convertELtoArray_latest(para_pcode, is_table) {
	var deferred = $.Deferred();
	/*if (is_Numeric(para_pcode)) {
		deferred.resolve(false);
		return deferred.promise();
	}*/
	if (is_table) {
		deferred.resolve(false);
		return deferred.promise();
	}
	var element_list1 = [];
	var att1 = [];  
	var pcode = '';
	if (para_pcode != null)
		pcode = para_pcode;
	else
		pcode = product_code;
	var rootPath = "/" + cnsd_pub_lang + "/data/stat_report/product/" + pcode;
	var indexPath  = "/en/data/stat_report/product/" + pcode + "/report_element_index.json";
    $.getJSON(getCacheFile(indexPath), function(data) {
		var arrList = data.elementindex;
        if (typeof arrList !== 'undefined') {
			if (arrList.length == 0) {
				deferred.resolve(false);
				return deferred.promise();
			}
			$.when(readOneElementFile(rootPath,arrList,0)).done(function(value){
				deferred.resolve(value);
			});          
        } else {
			deferred.resolve(false);
        }
    }).fail(function () {	// cannot open index element index  file
		deferred.resolve(false);
	});  
    return deferred.promise();
}

function findLatestIssue(pcode, is_table) {	// get the latest release record from product element and return the result for rendering on subject page
	var deferred = $.Deferred();
	$.when(convertELtoArray_latest(pcode, is_table)).done(function(data) {
		if (data !== false) {
			if (typeof data.elementlist !== 'undefined') {
				if (data.elementlist.length > 0) {	//sort the elementlist by release date  desc 
                    var arr_element = data['elementlist'];
					var arr_att = data['att'];
					for (var y = 0; y < arr_element.length; y++) {
						arr_element[y]['Element_ID'] = parseInt(arr_element[y]['Element_ID']);
					}
					var arr_element = multiSort(arr_element, {
						Release_Date_Soft: 'desc',
						Element_ID: 'desc'
					});
					//get related att 
					if (arr_att.length > 0) {
						arr_att = $.grep(arr_att, function(element, index) {
							  return element.Element_ID == arr_element[0].Element_ID;
						  });
					}
					deferred.resolve({
						'element': arr_element[0],
						'att': arr_att
					});
				} else {
					deferred.resolve(false);
				}
			} else {
				deferred.resolve(false);
			}
		} else {
			deferred.resolve(false);
		}
	});
    return deferred.promise();
}

function loadLangRes() {
	$("*").contents().filter(function () {
		return this.parentNode.getAttribute('langresource');
	}).each(function () {
		var x = $(this).parent().attr('langresource');
		x = getLangCaption(x);
		$(this).parent().html(x);
	});
}

function getURLParameter(sParam) {
    var sPageURL = window.location.search.substring(1);
    var sURLVariables = sPageURL.split('&');
    for (var i = 0; i < sURLVariables.length; i++) {
        var sParameterName = sURLVariables[i].split('=');
        if (sParameterName[0] == sParam) {
            return sParameterName[1];
        }
    }
}

function getParentSubjectCodeList(subject_object, subject_list) {
    if (subject_object.Parent_Subject_ID == null) {
        return [subject_object.Subject_Code];
    }    
    var parent_subject_object = subject_list[subject_object.Parent_Subject_ID];
    var code_list = getParentSubjectCodeList(parent_subject_object, subject_list);
    code_list.push(subject_object.Subject_Code);
    return code_list;
}

"use strict";
function getDateString(sDate,useLongFormat) {	// change the date format from yyyy/mm/dd to cnsd_pub_language specific short date     
    var str_yyyy = sDate.substring(0, 4);
    var str_mm = sDate.substring(5, 7);
    var str_dd = sDate.substring(8, 10);
    var strxxx = '';
    //edit by dicky 20201014 suppress leading zero for month and day
    if (str_mm.substring(0,1) == '0')
		str_mm = str_mm.substring(1,2);
    if (str_dd.substring(0,1) == '0')
		str_dd = str_dd.substring(1,2);    
    //end of edit 
    if (cnsd_pub_lang == 'en') {
		if (useLongFormat==true){
			//strxxx =  str_dd + ' ' + eval('month_names_long_' + cnsd_pub_lang)[str_mm - 1] + ' ' + str_yyyy ;
			strxxx =  str_dd + ' ' + month_names_long_en[str_mm - 1] + ' ' + str_yyyy ;
		}
		else{            
            //strxxx =  str_dd + ' ' + eval('month_names_' + cnsd_pub_lang)[str_mm - 1] + ' ' + str_yyyy ;
			strxxx =  str_dd + ' ' + month_names[cnsd_pub_lang][str_mm - 1] + ' ' + str_yyyy ;
		}
    } else {
        //strxxx =  str_yyyy + '年' + eval('month_names_' + cnsd_pub_lang)[str_mm - 1] + str_dd + '日';
		strxxx =  str_yyyy + '年' + month_names[cnsd_pub_lang][str_mm - 1] + str_dd + '日';
    }
    return strxxx;
}

function getSizeDesc(filesize) {
	if (filesize == null) {
		return '';
	}
	if (filesize == 0) {
		return '';
	}
	if (filesize > (1024 * 1024)) {
		return (Math.round(filesize/(1024 * 1024)*10)/10) +'MB';
	} else {
		return (Math.round(filesize / 1024 *10) /10 ) + 'k';
	}
}

/* function checkSP(pcode) {	// base on user query on subject and product code to find the result if not found then alert error page
    var ret = false; 
    var deferred = $.Deferred();
    var subject_data_path = subject_data_dir + "report_index.json";
    $.getJSON(getCacheFile(subject_data_path), function (data) {
        if (typeof data == 'undefined') {
            ret = false;
        }
        arr_product_index = data.productIndex;
        var objData = $.grep(arr_product_index, function(element,index) {
            return element.Product_Code == pcode; 
        });
        if (typeof objData !== 'undefined') {
			if (objData.length > 0)
				ret = true; 
        } else {
			ret  = false;
        }
        deferred.resolve(ret);        
	}).fail(function() {	  
		deferred.resolve(false);
	});
	return deferred.promise();
} */
function checkSP(pcode) {
    var ret = false; 
    var deferred = $.Deferred();

    

    // Helper to build subject data path
    function buildSubjectPath(scode) {
        return "../" + cnsd_pub_lang + "/data/stat_report/subject/" + scode + "/report_index.json";
    }

    // 🔹 Function to query a subject code
    function querySubject(scode) {
        var subject_data_path = buildSubjectPath(scode);
        return $.getJSON(getCacheFile(subject_data_path))
            .then(function (data) {
                if (!data || !data.productIndex) return false;
                var arr_product_index = data.productIndex;
                var objData = $.grep(arr_product_index, function (element) {
                    return element.Product_Code == pcode.toUpperCase();
                });
                return (objData && objData.length > 0);
            })
            .catch(function () {
                return false;
            });
    }

    // 🔹 First try with the global subject_code
    querySubject(subject_code).then(function (found) {
        if (found) {
            ret = true;
            deferred.resolve(ret);
        } else {
            // 🔹 If not found, check mapping
            if (subjectCodeMap.hasOwnProperty(subject_code)) {
                var newScode = subjectCodeMap[subject_code];
                querySubject(newScode).then(function (foundMapped) {
                    ret = foundMapped;
                    if (foundMapped) {
                        // ✅ Update global subject_code
                        subject_code = newScode;

                        // ✅ Update the address bar (without reload)
                        const url = new URL(window.location.href);
                        url.searchParams.set("scode", newScode);
                        history.replaceState(null, "", url.toString());
                    }
                    deferred.resolve(ret);
                });
            } else {
                deferred.resolve(false);
            }
        }
    });

    return deferred.promise();
}

/* 
function getProductTitle(pcode) {	// check 
    var ret = '';
    var deferred = $.Deferred();
    var subject_data_path = subject_data_dir + "report_index.json";
    $.getJSON(getCacheFile(subject_data_path), function (data) {
        if (typeof data == 'undefined') {      
            ret = ''; 
        }
        arr_product_index = data.productIndex;
        var objData = $.grep(arr_product_index, function(element,index) {
            return element.Product_Code==pcode.toUpperCase();
        }) ;
        if (typeof objData !== 'undefined') {
           if (objData.length > 0) {
              ret = objData[0].Product_Title;
            }
        } else{
            ret  = '';
        }
        deferred.resolve(ret);        
	});
	return deferred.promise();
} */

function getProductTitle(pcode) {
    var ret = '';
    var deferred = $.Deferred();

    // Helper to build subject data path
    function buildSubjectPath(scode) {
        return "../" + cnsd_pub_lang + "/data/stat_report/subject/" + scode + "/report_index.json";
    }

    // 🔹 Function to query a subject code
    function querySubject(scode) {
        var subject_data_path = buildSubjectPath(scode);
        return $.getJSON(getCacheFile(subject_data_path))
            .then(function (data) {
                if (!data || !data.productIndex) return '';
                var arr_product_index = data.productIndex;
                var objData = $.grep(arr_product_index, function (element) {
                    return element.Product_Code == pcode.toUpperCase();
                });
                return (objData && objData.length > 0) ? objData[0].Product_Title : '';
            })
            .catch(function () {
                return '';
            });
    }

    // 🔹 First try with the global subject_code
    querySubject(subject_code).then(function (title) {
        if (title) {
            ret = title;
            deferred.resolve(ret);
        } else {
            // 🔹 If not found, check mapping
            if (subjectCodeMap.hasOwnProperty(subject_code)) {
                var newScode = subjectCodeMap[subject_code];
                querySubject(newScode).then(function (mappedTitle) {
                    ret = mappedTitle;
                    if (mappedTitle) {
                        // ✅ Update global subject_code
                        subject_code = newScode;

                        // ✅ Update the address bar (preserve anchor if any)
                        const url = new URL(window.location.href);
                        url.pathname = url.pathname.replace(/scode\d+\.html/, `scode${newScode}.html`);
                        history.replaceState(null, "", url.toString());
                    }
                    deferred.resolve(ret);
                });
            } else {
                deferred.resolve('');
            }
        }
    });

    return deferred.promise();
}


function genErrorPage() {
	window.location.href = '/' + cnsd_pub_lang + '/';
}

function cnsd_publication_genShowMore_old(moreTextid , btnid) {
	if (moreTextid ==null)
		var moreText = document.getElementById("more");
	else
		var moreText = document.getElementById(moreTextid);
	if (btnid ==null)
		var btnText = document.getElementById("cnsd_morelessBtn");
	else
		var btnText = document.getElementById(btnid);
	if (moreText.style.display === "inline") {
		btnText.innerHTML = show_text.more2;
		moreText.style.display = "none";
	} else {
		btnText.innerHTML = show_text.less2;
		moreText.style.display = "inline";
	}
}

function cnsd_publication_genShowMore(btnid,classes_to_hide) {  
	$("table #" + btnid).each(function() {
		$(this).toggleClass('iscollapse');
	});
	$("." + classes_to_hide).each(function() {
		$(this).toggleClass('hide');
	});  
	if ($("table #" + btnid).hasClass('iscollapse')) {
		$("table #" + btnid).each(function() {
			$(this).html( show_text.more2);
		});   
	} else {
		$("table #" + btnid).each(function() {
			$(this).html( show_text.less2);
		});
	}  
}

function cnsd_publication_genPlusMinus(moreTextid, btnid) {
	if (moreTextid ==null)
		var moreText = document.getElementById("more");
	else
		var moreText = document.getElementById(moreTextid);
	if (btnid ==null)  
		var btnText = document.getElementById("cnsd_morelessBtn");
	else
		var btnText = document.getElementById(btnid);
	if (moreText.style.display === "block") {
		btnText.innerHTML = show_text.more;
		moreText.style.display = "none";
	} else {
		btnText.innerHTML = show_text.less;
		moreText.style.display = "block";
	}
	applyKeyword();
}

function genCoverImageText(obj_record) {
	if (obj_record.icf_en == null && obj_record.icf_tc == null) {
		return "";
	}
	var str = "";
	if (obj_record.Lang_ID == 4) {	
		//separate eng and chinese version 
        // follow the current cnsd_pub_lang folder
        if (obj_record.icf_tc == null) {
			file_name = en_attachment_path + obj_record.icf_en;
		} else {
			file_name = (cnsd_pub_lang == "tc") ? en_attachment_path + obj_record.icf_tc : (cnsd_pub_lang == "sc") ? en_attachment_path + obj_record.icf_tc : en_attachment_path + obj_record.icf_en;
        }
    } else if (obj_record.Lang_ID == 7) {	//tri lingual
        //get source 
         file_name = (cnsd_pub_lang == "tc") ? en_attachment_path + obj_record.icf_tc : (cnsd_pub_lang == "sc") ? en_attachment_path + obj_record.icf_sc : en_attachment_path + obj_record.icf_en;        
    } else if (obj_record.Lang_ID == 1 || obj_record.Lang_ID == 5) {
        // bilingual
        // get from en folder
        file_name = en_attachment_path + obj_record.icf_en;
    } else if (obj_record.Lang_ID == 6) {
        // trad chinese version only 
        // get from tc folder 
        file_name = en_attachment_path + obj_record.icf_tc;
    }
	str = '<img src="' +  file_name + '">';
    return str;
}

function haveAccFile2(obj_att,pcode) {	// pass element id to get the att
    var ret = false; 
    var deferred = $.Deferred();
	if (typeof obj_att !== 'undefined') {	//if only one acc file just show the related icon and link otherwise show more button
		if (obj_att.length > 1) {
			ret = 'more';
		} else if (obj_att.length == 1) {
			ret = genFileDownloadLink3(obj_att,true,true,pcode);
		}
	}
	deferred.resolve(ret);        
    return deferred.promise();
}

function haveAccFile(obj_record) {	// pass element id to get the att
    var ret = false; 
    var deferred = $.Deferred();
    var arr_att = []; 
    var element_data_path ; 
    var pcodeTarget = obj_record.Product_Code; 
    element_data_path =  "../" + cnsd_pub_lang + "/data/stat_report/product/" + pcodeTarget + "/report_element.json";
	$.getJSON(getCacheFile(element_data_path), function (data) {
		arr_att = data.att;
		if (typeof arr_att !== 'undefined') {
			var objFD = [];
			objFD = $.grep(arr_att, function(element,index) {
				return element.Element_ID == obj_record.last_element_id;                         
			});
			//if only one acc file just show the related icon and link otherwise show more button
			if (typeof objFD !== 'undefined') {
				if (objFD.length > 1) {
					ret = 'more';
				} else if (objFD.length == 1) {
					ret = genFileDownloadLink3(objFD,true,true,pcodeTarget);
				}
			}
		}
		deferred.resolve(ret);
	});
    return deferred.promise();
}

"use strict";
function genFileDownloadLink2(obj_record, hideSize, regenPath) {	//used in detail section of the product page 
	if (regenPath == true) {
		current_attachment_path  = statreport_data_dir + obj_record['Product_Code'] + "/att/";
		en_attachment_path = "../en/data/stat_report/product/" + obj_record['Product_Code'] + "/att/";
		tc_attachment_path = "../tc/data/stat_report/product/" + obj_record['Product_Code'] + "/att/";
		sc_attachment_path = "../sc/data/stat_report/product/" + obj_record['Product_Code'] + "/att/";
    }
 	if (typeof obj_record.en_file == 'undefined' && typeof obj_record.chi_file == 'undefined') { 
		return null;
    }    
    var file_name;
    var file_path;
    var file_size="";
    var str = "";
    if (obj_record.Lang_ID == 4) {	//separate eng and chinese version 
        // follow the current cnsd_pub_lang folder        
        if ((typeof obj_record.en_file == 'undefined' || obj_record.en_file == null) && cnsd_pub_lang == "en") { 
			return null;
        }    
        if ((typeof obj_record.chi_file == 'undefined'  || obj_record.chi_file == null) && (cnsd_pub_lang == "tc" || cnsd_pub_lang == "sc")) { 
			return null;
		}
        file_name = (cnsd_pub_lang == "tc") ? obj_record.chi_file : (cnsd_pub_lang == "sc") ? obj_record.chi_file : obj_record.en_file;
        file_path = (cnsd_pub_lang == "tc") ? tc_attachment_path + obj_record.chi_file : (cnsd_pub_lang == "sc") ? tc_attachment_path + obj_record.chi_file : en_attachment_path + obj_record.en_file;
        file_size = (cnsd_pub_lang == "tc") ? obj_record.chi_file_size : (cnsd_pub_lang == "sc") ? obj_record.chi_file_size : obj_record.en_file_size;
    } else if (obj_record.Lang_ID == 7) {	//tri lingual        
        if ((typeof obj_record.en_file == 'undefined' || obj_record.en_file == null) && cnsd_pub_lang == "en") { 
			return null;
        }    
        if ((typeof obj_record.chi_file == 'undefined' || obj_record.chi_file == null) && (cnsd_pub_lang == "tc" || cnsd_pub_lang == "sc")) {
			return null;
        }
        if ((typeof obj_record.schi_file == 'undefined'  || obj_record.schi_file == null) && cnsd_pub_lang == "sc") {
			return null;
        }
        file_name = (cnsd_pub_lang == "tc") ? obj_record.chi_file : (cnsd_pub_lang == "sc") ? obj_record.schi_file : obj_record.en_file;
        file_path = (cnsd_pub_lang == "tc") ? tc_attachment_path + obj_record.chi_file : (cnsd_pub_lang == "sc") ? sc_attachment_path + obj_record.schi_file : en_attachment_path + obj_record.en_file;
        file_size = (cnsd_pub_lang == "tc") ? obj_record.chi_file_size : (cnsd_pub_lang == "sc") ? obj_record.schi_file_size : obj_record.en_file_size;
    } else if (obj_record.Lang_ID == 1 || obj_record.Lang_ID == 5 ) {	// bilingual
        // get from en folder
        if (obj_record.en_file == null)  {
			return null;
        }
        file_name = obj_record.en_file;
        file_path = en_attachment_path + obj_record.en_file;
        file_size = obj_record.en_file_size;
    } else if (obj_record.Lang_ID == 6) {	// trad chinese version only 
        // get from tc folder 
        if ((typeof obj_record.chi_file == 'undefined'  || obj_record.chi_file == null) && cnsd_pub_lang == "tc") {
			return null;
        }        
        file_name = obj_record.chi_file;
        file_path = tc_attachment_path + obj_record.chi_file;
        file_size = obj_record.chi_file_size;
	}
    file_path = en_attachment_path + file_name;
    // diff presentation method for  diff file type
	var objButton = document.createElement('a');
	objButton.setAttribute('href',file_path);
	objButton.setAttribute('target','_blank');
	objButton.classList.add('pdl');
	if (typeof hideSize === 'undefined') {
		objButton.setAttribute('role','button');
		objButton.classList.add('btn');
		objButton.classList.add('btn-primary-outline');
		objButton.classList.add('btn-sm');
	}
	objImg = document.createElement('img');
	objImg.setAttribute('title',element_text.mainDownload);
	objImg.setAttribute('alt',element_text.mainDownload);
	if (!file_name) {
		return null;
	}
	var file_ext =  file_name.split('.').pop().toUpperCase();
	switch (file_ext) {
		case "XLS":
		case "XLSX":
			objImg.setAttribute('src',excel_icon_path);
            break;
		case "ZIP":
			objImg.setAttribute('src',zip_icon_path);                
			break;
		case "CSV":
			objImg.setAttribute('src',csv_icon_path);
            break;
		case "XML":
			objImg.setAttribute('src',xml_icon_path);
            break;
		case "PDF":
			objImg.setAttribute('src',pdf_icon_path);
            break;
	}
	str = '(';
	var strSize = getSizeDesc(file_size);
	str  = str + strSize + ')';
	objText = document.createTextNode(str);
	objButton.appendChild(objImg);
	if (typeof hideSize === 'undefined') {
        objButton.appendChild(objText);
	}
	return objButton;
}

function genFileDownloadLink3(obj_record, hideDesc, regenPath,pcode) {
	if (regenPath == true) {
		current_attachment_path  = statreport_data_dir + pcode + "/att/";
		en_attachment_path = "../en/data/stat_report/product/" + pcode + "/att/";
		tc_attachment_path = "../tc/data/stat_report/product/" + pcode + "/att/";
		sc_attachment_path = "../sc/data/stat_report/product/" + pcode + "/att/";
	}
	//used in rendering button for accompanying download files
    if (obj_record.length == 1) {	// only show button instead of dropdown in case only one file to download
     	if (obj_record[0].File_Name == null) { 
			return null;
		}        
        var file_path;
        var file_size="";
        var str = "";        
        // get from en folder         
        // in the format of {title}{a href="{filepath}"}{img src="" title=""}{a}
       file_path = en_attachment_path + obj_record[0].File_Name;
       file_size = obj_record[0].file_size;
       title = obj_record[0].file_title;
       var objButton = document.createElement('span');
       var objTtitle = document.createTextNode(title+' ');
       if (hideDesc !=true)
         objButton.appendChild(objTtitle);
       var objLink = document.createElement('a');
       objLink.setAttribute('href',file_path);
       objLink.setAttribute('target','_blank');
	   //add log    
		objLink.classList.add('pdl');
        var file_ext =  file_path.split('.').pop().toUpperCase();
		objImg = document.createElement('img');
		objImg.setAttribute('title',element_text.mainDownload);
		objImg.setAttribute('alt',element_text.mainDownload);
		switch (file_ext) {
			case "XLS":
            case "XLSX":
				objImg.setAttribute('src',excel_icon_path);
                break; 
            case "ZIP":
				objImg.setAttribute('src',zip_icon_path);                
                 break;
            case "CSV":
                objImg.setAttribute('src',csv_icon_path);                
				break;
            case "XML":
                objImg.setAttribute('src',xml_icon_path);                
				break;
            case "PDF":
				objImg.setAttribute('src',pdf_icon_path);    
				break;
		}
		str = ' (';
		var strSize = getSizeDesc(file_size);
		str  = str + strSize + ')';
		objText = document.createTextNode(str);
		objLink.appendChild(objImg);
		objButton.appendChild(objLink);
		return objButton;
    } else {	// render dropdown button for multiple files download
        var objDropdown = document.createElement('div');
        objDropdown.classList.add('dropdown');
        var objButton = document.createElement('button');
        objButton.setAttribute('type','button');
        objButton.classList.add('btn');
        objButton.classList.add('btn-primary-outline');
        objButton.classList.add('btn-sm');
        objButton.classList.add('dropdown-toggle');
        objButton.setAttribute('data-bs-toggle','dropdown');        
        var objImg = document.createElement('img');
        objImg.setAttribute('src',tabledownload_icon_path);
		objImg.setAttribute('class','decor');										  
        objButton.appendChild(objImg);
        var buttonCaption = element_text.acBtn;
        var objText  = document.createTextNode(' ' + buttonCaption);
        objButton.appendChild(objText);
        objDropdown.appendChild(objButton);
        var objDropDownMenu = document.createElement('div');
        objDropDownMenu.classList.add('dropdown-menu');
        objDropDownMenu.classList.add('dropdown-menu-right');
        for (i = 0; i < obj_record.length; i++) {
            if (obj_record[i].File_Name != null) {
				var file_path;
				var file_size = "";
				var str = "";            
                // get from en folder     
				file_path = en_attachment_path + obj_record[i].File_Name;
				file_size = obj_record[i].file_size;
				var objLink = document.createElement('a');
				objLink.classList.add('dropdown-item');
				objLink.setAttribute('href',file_path);
				//add log
				objLink.classList.add('pdl');
				objLink.setAttribute('target','_blank');
                var file_ext =  file_path.split('.').pop().toUpperCase();
                objImg2 = document.createElement('img');
                switch (file_ext) {
                    case "XLS":
                    case "XLSX":                        
                        objImg2.setAttribute('src',excel_icon_path);
						break;
                    case "CSV":
                        objImg2.setAttribute('src',csv_icon_path);         
						break;
					case "XML":
						objImg.setAttribute('src',xml_icon_path);                
						break;
                    case "PDF":
						objImg2.setAttribute('src',pdf_icon_path);    
						break;
                    case "ZIP":
						objImg2.setAttribute('src',zip_icon_path);
						break;
                }
                str = ' (';
				var strSize = getSizeDesc(file_size);
				var strTitle = obj_record[i].file_title;
				str = str + strSize + ') ' + strTitle;
                objText = document.createTextNode(str);
                objLink.appendChild(objImg2);
                objLink.appendChild(objText);
                objDropDownMenu.appendChild(objLink);
            }
        }
        objDropdown.appendChild(objDropDownMenu);
        return objDropdown;
	}
}

function genFileDownloadLink4(obj_record) {
    //return download link of main file only
    //used on product page all issue section
 	if (obj_record.en_file == null && obj_record.chi_file == null) { 
        return null;
	}    
    var file_name;
    var file_size="";
    var str = "";
    if (obj_record.Lang_ID == 4) {
        //separate eng and chinese version 
        // follow the current cnsd_pub_lang folder
        //get source 
        if ((typeof obj_record.en_file == 'undefined' || obj_record.en_file == null)&& cnsd_pub_lang == "en") { 
			return null;
        }    
        if ((typeof obj_record.chi_file == 'undefined' || obj_record.chi_file == null) && (cnsd_pub_lang == "tc" || cnsd_pub_lang == "sc")) {
			return null;
        }
        file_name = (cnsd_pub_lang == "tc") ?  obj_record.chi_file : (cnsd_pub_lang == "sc") ?  obj_record.chi_file :  obj_record.en_file;
        file_size = (cnsd_pub_lang == "tc") ? obj_record.chi_file_size : (cnsd_pub_lang == "sc") ? obj_record.chi_file_size : obj_record.en_file_size;
    } else if (obj_record.Lang_ID == 7) {	//tri lingual
        // follow the current cnsd_pub_lang folder
        //get source 
        if ((typeof obj_record.en_file == 'undefined' || obj_record.en_file == null) && cnsd_pub_lang == "en") {
			return null;
        }    
        if ((typeof obj_record.chi_file == 'undefined' || obj_record.chi_file == null) && cnsd_pub_lang == "tc") {
			return null;
        }
        if ((typeof obj_record.schi_file == 'undefined' || obj_record.schi_file == null) && cnsd_pub_lang == "sc") {
			return null;
        }
        file_name = (cnsd_pub_lang == "tc") ? obj_record.chi_file : (cnsd_pub_lang == "sc") ?  obj_record.schi_file : obj_record.en_file;
        file_size = (cnsd_pub_lang == "tc") ? obj_record.chi_file_size : (cnsd_pub_lang == "sc") ? obj_record.schi_file_size : obj_record.en_file_size;
    } else if (obj_record.Lang_ID == 1 || obj_record.Lang_ID == 5) {	// bilingual
        // get from en folder
        file_name = obj_record.en_file;
        file_size = obj_record.en_file_size;
    } else if (obj_record.Lang_ID == 6) {	// trad chinese version only 
        // get from tc folder
        if ((typeof obj_record.chi_file == 'undefined' || obj_record.chi_file == null) && cnsd_pub_lang == "tc") {
			return null;
        }
        file_name = obj_record.chi_file;
        file_size = obj_record.chi_file_size;
    }    
    file_name = en_attachment_path + file_name;
	objLink = document.createElement('a');
	objLink.setAttribute('href',file_name);
	objLink.setAttribute('target','_blank');
	//add log
	objLink.setAttribute('class','pdl');
	objImg = document.createElement('img');
	objImg.setAttribute('title', element_text.mainDownload);
	objImg.setAttribute('alt', element_text.mainDownload);   
    var file_ext =  file_name.split('.').pop().toUpperCase();    
    switch (file_ext) {
		case "XLS":
		case "XLSX":
			objImg.setAttribute('src',excel_icon_path);
            break;
		case "CSV":
			objImg.setAttribute('src',csv_icon_path);
            break;
		case "ZIP":
			objImg.setAttribute('src',zip_icon_path);                
            break;
		case "XML":
			objImg.setAttribute('src',xml_icon_path);                
            break;
		case "PDF":
			objImg.setAttribute('src',pdf_icon_path);    
			break;
      }
	  objLink.appendChild(objImg);
	  return objLink;
}

function genFileDownloadLink5(obj_record) {
 	if (obj_record.File_Name == null) { 
		return null;
	}    
    var file_name;
    var file_size="";
    var str = "";
	// get from en folder
	file_name = en_attachment_path + obj_record.File_Name;
	file_size = obj_record.file_size;
    // diff presentation method for  diff file type
	var file_ext =  file_name.split('.').pop().toUpperCase();
	switch (file_ext) {
		case "XLS":
		case "XLSX":
			var objA = document.createElement('img');
			objA.setAttribute("src",excel_icon_path);
			objA.addEventListener("click", function() {
				download5(obj_record.Element_ID,obj_record.sequence);
			});
			objA.addEventListener("mouseover", function() {
				objA.setAttribute("style","cursor:pointer");
			});
			return objA;
            break;
		case "ZIP":
			str = 'ZIP (';
			var strSize = getSizeDesc(file_size);
			str  = str + strSize + ')';
			var objA = document.createElement('a');
			objA.appendChild(document.createTextNode(str));
			objA.addEventListener("click", function() {
				download5(obj_record.Element_ID,obj_record.sequence);
			});
			objA.addEventListener("mouseover", function() {
				objA.setAttribute("style","cursor:pointer");
			});
			return objA;
			break;
		case "CSV":
			var objA = document.createElement('img');
			objA.setAttribute("src",csv_icon_path);
			objA.addEventListener("click", function() {
				download5(obj_record.Element_ID,obj_record.sequence);
			});
			objA.addEventListener("mouseover", function() {
				objA.setAttribute("style","cursor:pointer");
			});
			return objA;
            break;
		case "PDF":
			str = 'PDF (';
			var strSize = getSizeDesc(file_size);
			str  = str + strSize + ')';
			var objA = document.createElement('a');
			objA.appendChild(document.createTextNode(str));
			objA.addEventListener("click", function() {
				download5(obj_record.Element_ID,obj_record.sequence);
			});
			objA.addEventListener("mouseover", function() {
				objA.setAttribute("style","cursor:pointer");
			});
			return objA;
            break;
	}
}

function download(pid) {	// define the action taken while clicking the file download icons
	var obj_record = $.grep(statrpt.data, function(element,index) {
		return element.product_id == pid;
	});
	if (typeof obj_record == 'undefined') {
		return false;
	}
	obj_record = obj_record[0];
 	var file_name = "";
 	if (obj_record.Lang_ID == 4) {
        //separate eng and chinese version 
        // follow the current cnsd_pub_lang folder
        //get source 
        file_name = (cnsd_pub_lang == "tc") ? tc_attachment_path + obj_record.chi_file : (cnsd_pub_lang == "sc") ? tc_attachment_path + obj_record.chi_file : en_attachment_path + obj_record.en_file;
    } else if (obj_record.Lang_ID == 1 || obj_record.Lang_ID == 5 ) {
        // bilingual
        // get from en folder 
        file_name = en_attachment_path + obj_record.en_file;
    } else if (obj_record.Lang_ID == 6) {
        // trad chinese version only 
        // get from tc folder 
        file_name = tc_attachment_path +  obj_record.chi_file;
    }   
    window.open(file_name);  
}

function download2() {	// define the action taken while clicking the file download icons
	var obj_record = detail_section.data;
	if (typeof obj_record =='undefined') {
		return false;
	}
 	var file_name = "";
 	if (obj_record.Lang_ID == 4) {
        //separate eng and chinese version 
        // follow the current cnsd_pub_lang folder
        //get source 
        file_name = (cnsd_pub_lang == "tc") ? tc_attachment_path + obj_record.chi_file : (cnsd_pub_lang == "sc") ? tc_attachment_path + obj_record.chi_file : en_attachment_path + obj_record.en_file;
    } else if (obj_record.Lang_ID == 1 || obj_record.Lang_ID == 5 ) {
        // bilingual
        // get from en folder 
        file_name = en_attachment_path + obj_record.en_file;
    } else if (obj_record.Lang_ID == 6) {
        // trad chinese version only 
        // get from tc folder 
        file_name = tc_attachment_path +  obj_record.chi_file;
    }   
    window.open(file_name);  
}

function download3(seq) {
	// define the action taken while clicking the file download icons
    var arr_otherfiles = detail_section.data.att;
	var obj_record = $.grep(arr_otherfiles, function(element,index) {
		return element.sequence == seq;
	});
	if (typeof obj_record =='undefined') {
		return false;
	}
	obj_record = obj_record[0];
 	var file_name = en_attachment_path + obj_record.File_Name;  
    window.open(file_name);  
}

function download4(eid) {
	var file_name="";
	// define the action taken while clicking the file download icons
    var obj_record = $.grep(all_issue_section.data, function(element, index) {
		return element.Element_ID==eid ;                              	
	});
    obj_record = obj_record[0];
	if (typeof obj_record == 'undefined') {
		return false;
	}
 	if (obj_record.Lang_ID == 4) {
        //separate eng and chinese version 
        // follow the current cnsd_pub_lang folder
        //get source 
        file_name = (cnsd_pub_lang == "tc") ? tc_attachment_path + obj_record.chi_file : (cnsd_pub_lang == "sc") ? tc_attachment_path + obj_record.chi_file : en_attachment_path + obj_record.en_file;
    } else if (obj_record.Lang_ID == 1 || obj_record.Lang_ID == 5) {
        // bilingual
        // get from en folder
        file_name = en_attachment_path + obj_record.en_file;
    } else if (obj_record.Lang_ID == 6) {
        // trad chinese version only 
        // get from tc folder 
        file_name = tc_attachment_path +  obj_record.chi_file;
    }   
    window.open(file_name);  
}

function download5(eid,seq) {
	// define the action taken while clicking the file download icons
	var arr_element = $.grep(all_issue_section.data, function(element, index) {
		return element.Element_ID == eid;
	});
    var arr_otherfiles = arr_element[0].att;
	var obj_record = $.grep(arr_otherfiles, function(element, index) {
		return  element.sequence == seq;
	});	
	obj_record = obj_record[0];
	if (typeof obj_record =='undefined') {
		return false;
	}
 	var file_name = "";
    file_name = en_attachment_path + obj_record.File_Name;
    window.open(file_name);  
}

"use strict";
function multiSort(array) {
	var sortObject = arguments.length > 1 && arguments[1] !== undefined ? arguments[1] : {};
	var sortKeys = Object.keys(sortObject); // Return array if no sort object is supplied.
	if (!sortKeys.length) {
		return array;
	} // Change the values of the sortObject keys to -1, 0, or 1.
	for (var key in sortObject) {
		sortObject[key] = sortObject[key] === 'desc' || sortObject[key] === -1 ? -1 : sortObject[key] === 'skip' || sortObject[key] === 0 ? 0 : 1;
	}
	var keySort = function keySort(a, b, direction) {
		direction = direction !== null ? direction : 1;
		if (a === b) {      // If the values are the same, do not switch positions.
			return 0;
		} // If b > a, multiply by -1 to get the reverse direction.
		return a > b ? direction : -1 * direction;
	};
	return array.sort(function (a, b) {
		var sorted = 0;
		var index = 0; // Loop until sorted (-1 or 1) or until the sort keys have been processed.
		while (sorted === 0 && index < sortKeys.length) {
			var _key = sortKeys[index];
			if (_key) {
				var direction = sortObject[_key];
				sorted = keySort(a[_key], b[_key], direction);
				index++;
			}
		}
		return sorted;
	});
}

function makeSubjectListbyID(subjectlist) {
    var arrSL = []; 
    jQuery.each(subjectlist, function(i, obj) {
		arrSL[obj.Subject_ID] = obj;
    });
    return arrSL;
}

function renderFullSubjectPath (callback) {    
	var subjectPath = "/" +  cnsd_pub_lang + "/data/stat_report/subject/" ;
	$.getJSON(getCacheFile(subjectPath + 'subject_master.json'), function (data) {
        var arrSubject = [];
        var subjectcode_list = [];
        arrSubject = data;
        arrSubjectListbyID = makeSubjectListbyID(arrSubject);
		var curSubjectRecord = arrSubject[subject_code];
		subjectcode_list = getParentSubjectCodeList(curSubjectRecord,arrSubjectListbyID);
		var subject_name_list =  build_subject_name(subjectcode_list,arrSubject);
		var str = subject_name_list.join(' ' + subject_path_seperator + ' ');
		str = subject_path.prefix() + ' ' + str ;
		// display subject header 
		$(subject_header_selector).html(curSubjectRecord.Subject_Name);
		document.title = caption_text.cnsd + curSubjectRecord.Subject_Name;
	});
}

function build_subject_name(arr_subject_code,arrSubject) {
    var name_list = [];
    for (var i = 0; i < arr_subject_code.length; i++) {
        var obj = arrSubject[arr_subject_code[i]];
        if (typeof obj !== 'undefined') {
            name_list.push(obj.Subject_Name);
        }
    }
    return name_list;
}

function compareSubject(subject_list){
	var deferred = $.Deferred();
	for (var s_index in subject_list) {
		if (p_scodes.indexOf(subject_list[s_index]['Subject_Code'].toString()) > -1) { 
			deferred.resolve(true);
			return deferred.promise();
		}
	}
	deferred.resolve(false);
	return deferred.promise();  
}

function sortAlphaNum(as,bs) {
	var a, b, a1, b1, i= 0, n, L,
    rx = /(\.\d+)|(\d+(\.\d+)?)|([^\d.]+)|(\.\D+)|(\.$)/g;
    if(as=== bs) return 0;
    a= as.toLowerCase().match(rx);
    b= bs.toLowerCase().match(rx);
    L= a.length;
    while(i<L){
        if(!b[i]) return 1;
        a1= a[i],
        b1= b[i++];
        if(a1!== b1){
            n= a1-b1;
            if(!isNaN(n)) return n;
            return a1>b1? 1:-1;
        }
    }
    return b[i]? -1:0;
 }

function sortAlphaNumbyTitle_en(as,bs) {     
	var a, b, a1, b1, i= 0, n, L,
    rx = /(\.\d+)|(\d+(\.\d+)?)|([^\d.]+)|(\.\D+)|(\.$)/g;
    if (as['title' ]=== bs['title']) return 0;
    a = as['title'].toLowerCase().match(rx);
    b = bs['title'].toLowerCase().match(rx);
    L = a.length;
    while(i < L) {
        if(!b[i]) return 1;
        a1= a[i],
        b1= b[i++];
        if(a1 !== b1) {
            n = a1 - b1;
            if(!isNaN(n)) return n;
            return a1 > b1 ? 1 : -1;
        }
    }
    return b[i] ? -1 : 0;
}
 
function sortAlphaNumbyTitle(as,bs) {
	if (cnsd_pub_lang=='en')
		return sortAlphaNumbyTitle_en(as, bs);
	else
		return 	sortAlphaNumbyTitle_cn(as, bs);	 
 } 
 
function sortAlphaNumbyTitle_cn(as,bs) {
	var a, b, a1, b1, i= 0, n, L, colonindexA,colonindexB,
	rx = /(\.\d+)|(\d+(\.\d+)?)|([^\d.]+)|(\.\D+)|(\.$)/g;	
	colonindexA = as['title'].indexOf('：');
	colonindexB = bs['title'].indexOf('：');	
	if (colonindexA > 0)
		as['title_temp'] = as['title'].substring(0, colonindexA);
	else
		as['title_temp'] = as['title'];
	if (colonindexB > 0)	
		bs['title_temp'] = bs['title'].substring(0, colonindexB);
	else
		bs['title_temp'] = bs['title'];	
	as['title_temp'] = as['title_temp'].replace('表','');
	bs['title_temp'] = bs['title_temp'].replace('表','');	
    if (as['title_temp'] === bs['title_temp']) return 0;
    a = as['title_temp'].toLowerCase().match(rx);
    b = bs['title_temp'].toLowerCase().match(rx);
    L = a.length;
    while(i < L) {
        if(!b[i]) return 1;
        a1 = a[i],
        b1 = b[i++];
        if(a1 !== b1) {
            n = a1 - b1;
            if (!isNaN(n)) return n;
            return a1 > b1 ? 1 : -1;
        }
    }
    return b[i] ? -1 : 0;
}	
 
function sortAlphaNumbyTitle_cn2(as,bs) {
	var a, b;	// convert to strings and force lowercase
	a = typeof as['title'] === 'string' ? as['title'].toLowerCase() : as['title'].toString();
    b = typeof bs['title'] === 'string' ? bs['title'].toLowerCase() : bs['title'].toString();
    return a.localeCompare(b);
}

$("nav>a").removeClass('text-muted');

$('.title_a').on('click',function() {
	var cls = $(".title_a").attr("class");
	if(cls == "title_a") {
		$(".title_a").attr("class", "title_a");
	} else {
		$(".title_a").attr("class", "p-2 title_a flex-fill");
	}
	$(this).addClass('active');
});

function setCookie(cname, cvalue, exdays) {
	var d = new Date();
	d.setTime(d.getTime() + (exdays * 24 * 60 * 60 * 1000));
	var expires = "expires="+ d.toUTCString();
	document.cookie = cname + "=" + cvalue + ";" + expires + ";path=/";
}

function getCookie(cname) {
	var name = cname + "=";
	var decodedCookie = decodeURIComponent(document.cookie);
	var ca = decodedCookie.split(';');
	for(var i = 0; i <ca.length; i++) {
		var c = ca[i];
		while (c.charAt(0) == ' ') {
			c = c.substring(1);
		}
		if (c.indexOf(name) == 0) {
			return c.substring(name.length, c.length);
		}
	}
	return "";
}	

function listenForShow(sectionid, callback) {
    var target = document.getElementById(sectionid);

	if (!target)
		return ;
    var observer = new MutationObserver(function(mutations) {
        mutations.forEach(function(mutation) {
            if (mutation.attributeName === "class") {
                if ($(target).hasClass("show")) {
                    callback(); // trigger your function
                }
            }
        });
    });

    observer.observe(target, { attributes: true });
}

function setDashboardSize()
{
		var $divElement = $('#viz1748415509812');								
		var $subject_width = $('#is_section');
		var $vizElement = $divElement.find('object').first();
		var width = $subject_width.outerWidth();
		if (oIsSC) {
			var vizElement = $vizElement[0];
			var name = vizElement.getElementsByTagName("param")[3].value;
			vizElement.getElementsByTagName("param")[3].value = name.replace("_TC_", "_SC_");
			var static_image = vizElement.getElementsByTagName("param")[6].value;
			vizElement.getElementsByTagName("param")[6].value = static_image.replace("_TC_", "_SC_");
			
			var language = vizElement.getElementsByTagName("param")[12].value;
			vizElement.getElementsByTagName("param")[12].value = language.replace(
				"zh-TW",
				"zh-CN"
			);
		}
		// Check if elements exist
		if ($divElement.length && $vizElement.length) {
			if (width >= 1176) {
				$('.tableau-device-param').attr('value', 'desktop');
				$vizElement.css({
					width: '100%',
					height: '750px'
				});
			} else if (width > 768) {
				$('.tableau-device-param').attr('value', 'tablet');
				$vizElement.css({
					width: '100%',
					height: '1427px'
				});
			} else {
				$('.tableau-device-param').attr('value', 'phone');
				$vizElement.css({
					width: '100%',
					height: '2027px'
				});
			}
			
			// Load Tableau viz script
			$('<script>', {
				src: 'https://public.tableau.com/javascripts/api/viz_v1.js'
			}).insertBefore($vizElement);
		}
	
}

$(document).ready(function () {
		listenForShow("is_link", function() {    
		setDashboardSize();
	});
	
});