document.write('<SCR'+'IPT type="text/JavaScript" charset="utf-8" src="/js/papaparse.min.js"></SCR'+'IPT>');

var ROW = 0;
var COLUMN = 1;
var ROW_LEFT = 0;
var ROW_RIGHT = 1;
var COLUMN_TOP = 2;
var COLUMN_BOTTOM = 3;
var TOP = 0;
var BOTTOM = 1;
var SV = 'sv';
var SP = 'sp';
var CV = 'cv';
var CV_ALL = 'cv_all';
var CC = 'cc';
var SAFE_CHARACTERS = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz-_';
var CHINESE_MONTH = ['一','二','三','四','五','六','七','八','九','十','十一','十二'];
var JSON_NULL = 'NULL';
var M3M = 'M3M';
var MM = 'MM';
var H = 'H';
var Q = 'Q';
var QoQ = 'QoQ';
var CCYY = 'CCYY';
var CCYY_F = 'FFYY';
var TOTAL = 'TOTAL';
var HIDDEN_CHART_CV_CC_CLASS_NAME_BY_CHART_X_AXIS = 'hidden_chart_cv_cc_x_axis';
var HIDDEN_CHART_CV_CC_CLASS_NAME = 'hidden_chart_cv_cc';
var HIDDEN_CHART_CV_CLASS_NAME = 'hidden_chart_cv';
var HIDDEN_CHART_SV_SP_CLASS_NAME = 'hidden_chart_sv_sp';
var CDM_CHECKBOX_CLASS_NAME = 'cdm_checkbox';
var na_sd_value = "9";
var last_bread_item = null;
var mdt_counter = [];
var mdt_counter_map = [];
var cc_counter = [];
var cc_counter_map = [];
var EN = 0;
var TC = 1;
var SC = 2;
var POSITION = '_p_';
var DISPLAY_ORDER = '_d_';
var SHOW_TOTAL = '_t_';
var TS_INDEX = 'TSI';
var DEFAULT_TABLE = 'default_table';
var TABLE_HEADER_CELL_ID_1 = 'tableHeaderCell1';
var table_notes = 'table_notes';

var all_mdt_list = [];
var all_sv_list = [];
var all_sd_list = [];
var all_sd_load = false;
var all_mdt_load = [];
var all_chart_load = [];
var all_chart_list = [];
var chart_container_list = { };
var cc_cell_id_map = [];
var mdt_without_table_all_load = false;
var href = window.location.href;
var parameter_index = href.indexOf('?');
var url_vars = {};
var api_popup = false;
var option_popup = false;
var no_popup = 'no_popup';
var download_excel = false;
var download_excel_excl = false;
var download_csv = false;
var download_csv_excl = false;
var download_csv_tabular = false;
var download_xml = false;
var download_sdmx = false;
var close_download = false;
var full_series = false;
var cacheMdtData = [];
var langDir = "en/";
var table_data_list = [];
var cmd_mdt_deferred = $.Deferred();
var page_has_chart = false;
var table_resolve = [];
var table_reject = [];
var cdm_text_data = null;
var table_order_footnote_index_id_counter = 0;
var table_order_footnote_index_map = [];
var icon_chart_table_init = false;
var last_window_width = 9999;
var note_data_array = [];	//different usages in map page and web_table page
var source_data_array = [];
var scrollMenuFlag = "";
var printClicked = false;
var allPrinted = false;
var escapeAccessLog = false;

var exportTableCellStyle = "border: none !important; background-color: transparent;";
const tv_name = "timeVariableName";
var escapeMdtProperties = ["obs_value", "sd_value", "ignore_sd_values", "tmp_ignore_sd_values"];
var indenpendent_tv_list = [ "CCYY", "FFYY" ];
var latest_tv_list = [{
	class_var: "H",
	max: "2"
}, {
	class_var: "Q",
	max: "4"
}, {
	class_var: "YTQ",
	max: "4"
}, {
	class_var: "MM",
	max: "12"
}, {
	class_var: "YTM",
	max: "12"
}, {
	class_var: "M3M",
	max: "12"
}, {
	class_var: "M12M",
	max: "12"
}];
var no_ccyy_tv = [ "M3M", "M12M" ];
if (!window.isWebReport && !window.isPic) {
	document.write('<SCR'+'IPT type="text/JavaScript" charset="utf-8" src="/js/cnsd_web_table.js"></SCR'+'IPT>');
}
document.write('<SCR'+'IPT type="text/JavaScript" charset="utf-8" src="/js/cnsd_pac.js"></SCR'+'IPT>');
document.write('<SCR'+'IPT type="text/JavaScript" charset="utf-8" src="/js/scrolling.js"></SCR'+'IPT>');
document.write('<SCR'+'IPT type="text/JavaScript" charset="utf-8" src="/js/cnsd_cdm_chart.js"></SCR'+'IPT>');
document.write('<SCR'+'IPT type="text/JavaScript" charset="utf-8" src="/js/cnsd_cdm_download.js"></SCR'+'IPT>');

function createTableData(table_id) {
	return {
		table_id: table_id,
		notes_data : [],
		ccyy_time_series_map_done: false
	};
}

function setTableLookupPath(lookup_path) {
	clearAllNotesAndSources();
	var temp_table_data_list = [];
	for (var i = 0; i < table_id_list.length; i++) {
		var table_id = table_id_list[i];
		var table_data = jQuery.extend(true, { }, table_data_list[table_id]);
		table_data.lookup_path = lookup_path;		
		var ccyy_show_list = [];	
		for (var lookup_index in lookup_path) {			
			var class_var = lookup_path[lookup_index].class_var;
			var class_code = lookup_path[lookup_index].class_code;			
			var cv_record = table_data.lang_data.cv_list[class_var];
			for (var ccg_index in cv_record.ccg_list) {
				var temp_ccg_record = cv_record.ccg_list[ccg_index];
				var temp_cc_list = temp_ccg_record.cc_list;
				if (class_code) {
					var cc_record = temp_cc_list[class_code];
					if (cc_record.has_data) {
						cc_record.show = true;
						if (cv_record.is_time_series) {
							if (class_var == CCYY) {									
								ccyy_show_list[class_code] = true;
								for (var c_index in table_data.ccyy_time_series_list) {
									var time_series_list = table_data.ccyy_time_series_list[c_index];
									for (var t_index in time_series_list) {
										if (time_series_list[t_index].ccyy_index == class_code) {
											time_series_list[t_index].ccyy_record.show = cc_record.show;
										}
										time_series_list[t_index].show = time_series_list[t_index].ccyy_record.show && time_series_list[t_index].time_series_record.show;
									}
								}
							} else {
								var time_series_list = table_data.ccyy_time_series_list[class_var];
								for (var t_index in time_series_list) {
									if (time_series_list[t_index].time_series_index == class_code) {
										time_series_list[t_index].time_series_record.show = cc_record.show;
									}
									time_series_list[t_index].show = time_series_list[t_index].ccyy_record.show && time_series_list[t_index].time_series_record.show;
								}
							}								
						}
					}
				} else {
					for (var ccg_j in table_data.component_data.table_component_ccg_list[class_var].ccg_list) {
						var itm = table_data.component_data.table_component_ccg_list[class_var].ccg_list[ccg_j];
						if (itm.show_total) {
							itm.cv_total_show = parseInt(itm.show_total);
						} else {
							itm.cv_total_show = 0;
						}
					}
				}
			}
		}		
		buildCdmTable(table_data, (i > 0));
		temp_table_data_list.push(table_data);
	}
	sleep(0).then(function () {	//delay the chart generation time for map_sev & map_ghs in order to initialize notes_data in table_data_list
		temp_table_data_list.forEach(function (v) {
			buildTableCharts(v);
		});
	});
}

function showNotFoundMsg(url, msg) {
	var message = msg ? msg : error_msg.file_missing;
	var idx = url.indexOf("?nocache");
	if (idx >= 0) {
		var file = url.substring(0, idx);
		idx = file.indexOf("/data/")
		if (idx >= 0) {
			file = file.substring(idx + 6);
		}		
		showMsg(message.replace("[FILE]", file));
	} else {
		showMsg(message.replace("[FILE]", url));
	}
}

function readTableComponent(dataDir, table_data, resolve) {
	$.getJSON(getCacheFile(dataDir + 'table_' + table_data.table_id + '_comp.json'), function (data) {
		if(data.length == 0){
			showNotFoundMsg(this.url);
			getTableListPage(table_data.table_id);
		}			
		table_data.componentLoaded = true;
		table_data.component_data = data;
		loadTableJsonData(dataDir, table_data);
	}).fail(function() {
		showNotFoundMsg(this.url);
		getTableListPage(table_data.table_id);
	});
	$.getJSON(getCacheFile(dataDir + langDir + 'table_' + table_data.table_id + '_lang.json'), function (data) {
		if(data.length == 0){
			showNotFoundMsg(this.url);
			getTableListPage(table_data.table_id);
		}
		table_data.langLoaded = true;
		table_data.lang_data_exp = clone(data);	//for pac export CSV (tabular & XML)
		rebuildPAC(data);
		table_data.lang_data = data;
		loadTableJsonData(dataDir, table_data);
	}).fail(function(e) {
		showNotFoundMsg(this.url);
		getTableListPage(table_data.table_id);
	});
	if (all_sd_list.length == 0) {
		$.getJSON(getCacheFile(dataDir + langDir + 'sd_lang.json'), function (data) {
			table_data.sdLoaded = true;
			table_data.sd_list = data;
			all_sd_list = data;
			loadTableJsonData(dataDir, table_data);
		}).fail(function() {
			showNotFoundMsg(this.url);
			getTableListPage();
		});
	} else {
		table_data.sdLoaded = true;
		table_data.sd_list = all_sd_list;
		loadTableJsonData(dataDir, table_data);
	}	
}

function initEvents() {	
	$(".excel").bind("click",function() { 
		generateDefault('Excel', false);
	});
	$(".excel_no_sd").bind("click",function() { 
		generateDefault('Excel', true);
	});
	$(".csv").bind("click",function() { 
		generateDefault('csv', false);
	});
	$(".csv_no_sd").bind("click",function() { 
		generateDefault('csv', true);
	});
	$(".csv_tabular").bind("click",function() { 
		generateDefault('csv_tabular', false);
	});
	$(".xml").bind("click",function() { 
		//generateXml();
		generateDefault('xml', false);
	});	
	$(".sdmx").bind("click",function() {
		var table_data = table_data_list[table_id_list[0]];
		loadSdmx(table_data).then(function (v) {
			if (v && v.length > 0) {
				generateSdmx();
			} else {
				errorLog("SDMX", "No SDMX can be downloaded");
			}
		});
	});
	$(".excel").bind('keypress',function (event) { 
		if(event.keyCode == 13) {
			generateDefault('Excel', false);
		}
	});
	$(".excel_no_sd").bind('keypress',function (event) { 
		if(event.keyCode == 13) {
			generateDefault('Excel', true);
		}
	});
	$(".csv").bind('keypress',function (event) { 
		if(event.keyCode == 13) {
			generateDefault('csv', false);
		}
	});
	$(".csv_no_sd").bind('keypress',function (event) { 
		if(event.keyCode == 13) {
			generateDefault('csv', true);
		}
	});
	$(".csv_tabular").bind('keypress',function (event) { 
		if(event.keyCode == 13) {
			generateDefault('csv_tabular', false);
		}
	});
	$(".xml").bind('keypress',function (event) { 
		if(event.keyCode == 13) {
			//generateXml();
			generateDefault('xml', false);
		}
	});
	$(".sdmx").bind('keypress',function (event) { 
		if(event.keyCode == 13) {
			$(".sdmx").click();
		}
	});
	if (typeof(table_id_list) !== 'undefined') {
		table_id_list.forEach(function (table_id) {
			if (!window.isWebReport) {
				var div = $("#" + table_id).parent()[0];
				if (!div) {
					div = $("#" + DEFAULT_TABLE).parent()[0];
				}
				if (div) {
					div.classList.add("pivotTableContainer");
					$(div).attr("onscroll", "pivotTableDivScrolling(this)");
				}
			}
			var temp_table_id_list = [];
			temp_table_id_list.push(table_id);		
			$(".excel_" + table_id).bind("click", {'temp_table_id_list' : temp_table_id_list}, function (event) { 
				generateDownload('Excel', event.data.temp_table_id_list, false);
			});
			$(".excel_no_sd_" + table_id).bind("click", {'temp_table_id_list' : temp_table_id_list},function (event) { 
				generateDownload('Excel', event.data.temp_table_id_list, true);
			});
			$(".csv_" + table_id).bind("click", {'temp_table_id_list' : temp_table_id_list},function (event) { 
				generateDownload('csv', event.data.temp_table_id_list, false);
			});
			$(".csv_no_sd_" + table_id).bind("click", {'temp_table_id_list' : temp_table_id_list},function (event) { 
				generateDownload('csv', event.data.temp_table_id_list, true);
			});
			$(".csv_tabular_" + table_id).bind("click", {'temp_table_id_list' : temp_table_id_list},function (event) { 
				generateDownload('csv_tabular', event.data.temp_table_id_list, false);
			});
			$(".excel_" + table_id).bind('keypress', {'temp_table_id_list' : temp_table_id_list},function (event) { 
				if(event.keyCode == 13) {
					generateDownload('Excel', event.data.temp_table_id_list, false);
				}
			});
			$(".excel_no_sd_" + table_id).bind('keypress', {'temp_table_id_list' : temp_table_id_list},function (event) { 
				if(event.keyCode == 13) {
					generateDownload('Excel', event.data.temp_table_id_list, true);
				}
			});
			$(".csv_" + table_id).bind('keypress', {'temp_table_id_list' : temp_table_id_list},function (event) { 
				if(event.keyCode == 13) {
					generateDownload('csv', event.data.temp_table_id_list, false);
				}
			});
			$(".csv_no_sd_" + table_id).bind('keypress', {'temp_table_id_list' : temp_table_id_list},function (event) { 
				if(event.keyCode == 13) {
					generateDownload('csv', event.data.temp_table_id_list, true);
				}
			});
			$(".csv_tabular_" + table_id).bind('keypress', {'temp_table_id_list' : temp_table_id_list},function (event) { 
				if(event.keyCode == 13) {
					generateDownload('csv_tabular', event.data.temp_table_id_list, false);
				}
			});
		});
	}
}

$(document).ready(function() {
	if (!$("#header") || $("#header").length === 0) {
		return;
	}
	if (!window.isWebReport && !window.isPic) {
		webTableInit();
		initEvents();
		var tags = window.location.href.split("#");
		if (tags && tags.length > 1) {
			var tag = tags[tags.length - 1];
			if (tag && (document.getElementById(tag) || document.getElementsByName(tag)[0])) {
				sleep(1000).then(function () {	//handle the 1st get request with bookmark
					scrollMenuFlag = "#" + tag;	//will be reset by other function if set before the timeout function
					handleScrolling();
				});
			} else {
				sleep(0).then(function () {
					$("#backToTopBtn").click();
				});
			}
		} else {
			sleep(0).then(function () {
				$("#backToTopBtn").click();
			});
		}
	}
});

function getMdtFilename(theme_id, stat_var, stat_pres, table_id, is_overview, is_short) {
	stat_pres = stat_pres.replaceAll("/", "slash");
	stat_var = stat_var.replaceAll("/", "slash");
	var overview_string = '';
	if (is_overview) {
		overview_string = 'Overview_';
	}
	var short_string = '';
	if (is_short) {
		short_string = 'Short_';
	}
	var filename = "MDT_" + theme_id + "_" + overview_string + short_string + stat_var + "_" + stat_pres + ".csv";
	if (table_id) {
		filename = "MDT_" + theme_id + "_" + overview_string + short_string + table_id + "_" + stat_var + "_" + stat_pres + ".csv";
	}
	filename = filename.replaceAll("%", "percent");
	filename = filename.replaceAll("$", "dollar");
	return filename;
}

function getMDT(dataDir, filename) {
	return getCacheFile(dataDir + filename);
	
}

function getMdtRecordWithoutExtraCondition(check_mdt, cv_used, table_data) {
	return getMdtListWithoutExtraCondition(check_mdt, cv_used, table_data)[0];
}

function getMdtListWithoutExtraCondition(check_mdt, cv_used, table_data) {
	var value_list = ['obs_value', 'sd_value', 'ignore_sd_values', 'mdt_obs_value_text', 'data-mdt_obs_value_no_sd_text', 'mdt_obs_value_no_sd_text', 'mdt_sv_index', 'mdt_sp_index'];
	var record_list = [];	
	var matched_mdt_record = null;
	for (var mdt_index in check_mdt) {
		var with_extra = false;
		var mdt_record = check_mdt[mdt_index];
		for (var key in mdt_record) {
			if (value_list.includes(key)) {
				continue;
			} else if (cv_used.indexOf(key) >= 0) {
				if (table_data) {
					var check_cc = mdt_record[key];
					if (check_cc) {
						var cv_record = table_data.lang_data.cv_list[key];
						var found_cc = false;
						for (var ccg_index in cv_record.ccg_list) {
							var ccg_record = cv_record.ccg_list[ccg_index];
							if (ccg_record.cc_list[check_cc]) {
								found_cc = true;
								break;
							}
						}						
						if (!found_cc) {
							with_extra = true;
						}
					}
				} else {
					continue;
				}
			} else if (mdt_record[key] != '') {
				//if (!table_data || !table_data.lang_data.cv_list[key] || table_data.lang_data.cv_list[key].is_time_series !== "1") {
					with_extra = true;
				/*} else {
					continue
				}*/
			}
		}		
		if (!with_extra) {
			record_list.push(mdt_record);
		}
	}
	return record_list;
}

function filterMdtFromLookupPath(temp_chart_mdt, mdt_lookup_path, cv_used) {
	for (var loopup_index in mdt_lookup_path) {
		var loopup_record = mdt_lookup_path[loopup_index];
		cv_used.push(loopup_record.class_var);
		if (loopup_record.class_code) {
			temp_chart_mdt = $.grep(temp_chart_mdt, function (obj) { return (obj[loopup_record.class_var] == loopup_record.class_code); });
		} else {
			temp_chart_mdt = $.grep(temp_chart_mdt, function (obj) { return (obj[loopup_record.class_var] == '') || (!obj[loopup_record.class_var]); });
		}
	}
	return temp_chart_mdt;
}

function sortCCYY(table_data) {
	var cv_ccyy = clone(table_data.component_data.table_component_ccg_list[CCYY]);
	if (cv_ccyy) {
		delete table_data.component_data.table_component_ccg_list[CCYY];
	}
	var cvs = clone(table_data.component_data.table_component_ccg_list);
	table_data.component_data.table_component_ccg_list = {};
	if (cv_ccyy) {
		table_data.component_data.table_component_ccg_list[CCYY] = cv_ccyy;
	}
	for (var cv in cvs) {
		table_data.component_data.table_component_ccg_list[cv] = cvs[cv];
	}
}

function computeTVSequence(table_data) {
	for (var itm in table_data.lang_data.cv_list) {
		var cv = table_data.lang_data.cv_list[itm];
		if (cv.is_time_series === "1") {
			var cv_comp = table_data.component_data.table_component_ccg_list[itm];
			if (cv_comp) {
				cv.tv_display_seq = table_data.component_data.table_component_ccg_list[itm].tv_display_seq || table_data.component_data.table_component_ccg_list[itm].display_order;
				cv.tv_display_seq = parseInt(cv.tv_display_seq);
				if (cv.tv_display_seq === 0) {
					for (var ccg in cv.ccg_list) {
						for (var cc in cv.ccg_list[ccg].cc_list) {
							cv.ccg_list[ccg].cc_list[cc].hidden_tv = true;
						}
					}
				}
			}
		}
	}
}

function loadTableJsonData(dataDir, table_data) {
	if (!table_data.componentLoaded || !table_data.langLoaded || !table_data.sdLoaded) {
		return;
	}
	var sv_index = 0;
	var sp_index = 0;
	var cv_index = 0;
	var ccg_index = 0;
	var cc_index = 0;
	if (typeof table_id_list !== 'undefined' && table_id_list.length == 1 && table_data.component_data.hide_table == 1) {
		if (table_data.component_data.tb_type === "0") {
			getTableListPage();
		} else {
			if (!table_data.component_data.chart_list || table_data.component_data.chart_list.length === 0) {
				getTableListPage();
			} else {	//web-table mode
				window.chart_only = true;
				$(".table_chart_div").hide();
				$(default_table).hide();
				$(".icon_chart").click();
			}
		}
	}
	table_data.component_data.rev_chrono = table_data.component_data.rev_chrono === "1" ? true : false;
	table_data.component_data.ori_rev_chrono = table_data.component_data.rev_chrono;
	table_data.mdt_all_load = false;
	table_data.chart_all_load = false;	
	// set meta tag
	if (table_data.component_data.keyword) {
		var meta = document.createElement('meta');
		meta.name = "keywords";
		meta.content = table_data.component_data.keyword;
		document.getElementsByTagName('head')[0].appendChild(meta);
	}	
	var release_date_string = '';
	for (var ccg in table_data.component_data.table_component_ccg_list) {
		table_data.component_data.table_component_ccg_list[ccg].ccg_list.forEach(function (v) {
			var total_position = parseInt(table_data.component_data.total_position);
			if (total_position >= 0) {
				if (parseInt(v.show_total) !== 0) {
					v.show_total = (total_position + 1).toString();
				}
			}
		});
	}
	if (table_data.component_data.release_date) {
		release_date_string = table_data.component_data.release_date;
		release_date_string = release_date_string.replace(new RegExp(/-/gm) ,"/"); 
		if (release_date_string.indexOf(".") != -1) {
			release_date_string = release_date_string.substring(0,release_date_string.indexOf("."));
		}
	}
	if (table_data.component_data.last_modified_date) {
		var published_date_string = table_data.component_data.last_modified_date;
		published_date_string = published_date_string.replace(new RegExp(/-/gm) ,"/"); 
		if (published_date_string.indexOf(".") != -1) {
			published_date_string = published_date_string.substring(0,published_date_string.indexOf("."));
		}		
		var last_modified_date_object = convertDateFromString(published_date_string);
		if (!window.isWebReport) {
			var temp_date = last_modified_date_object.getTime() / 1000;
			if (temp_date > published_at) {
				published_at = temp_date;
			}
			setBtmFnText();
		}		
		var release_date_obj = last_modified_date_object;
		if (release_date_string) {
			release_date_obj =convertDateFromString(release_date_string);
		}
		release_date_output = getReportDateString(release_date_obj);
		var last_revision_date_element = document.getElementById("last_revision_date");
		if (last_revision_date_element) {
			last_revision_date_element.innerHTML = release_date_output;
		}		
		var table_last_revision_date_element = document.getElementById(table_data.table_id + "_revision_date");
		if (table_last_revision_date_element) {
			table_last_revision_date_element.innerHTML = release_date_output;
		}		
		table_data.release_date_output = release_date_output;
	}	
	// set lang
	if (langDir.indexOf("tc") == 0) {
		table_data.lang = TC;
	} else if (langDir.indexOf("sc") == 0) {
		table_data.lang = SC;
	} else {
		table_data.lang = EN;
	}
	// build the title
	if (typeof cdm_text_file === 'undefined' && typeof default_demographics_lookup_path === 'undefined') {
		setTableTitle(table_data, true);
	} else if (typeof cdm_text_file === 'undefined'){
		setTableTitle(table_data, false);
	}
	table_data.theme_id = table_data.component_data.theme_id;
	table_data.mdt_load = [];
	table_data.mdt_data = [];
	// cv fields
	table_data.time_series_counter = 0;
	table_data.cv_map = [];
	table_data.cv_index_map = [];
	table_data.cc_map = [];
	table_data.cc_index_map = [];
	computeTVSequence(table_data);	
	for (var class_var in table_data.lang_data.cv_list) {
		if (table_data.lang_data.cv_list[class_var].is_time_series == 1) {
			table_data.time_series_counter++;
		}		
		var temp_ccg_list = table_data.lang_data.cv_list[class_var].ccg_list;
		if (table_data.cv_index_map[class_var] === undefined) {
			cv_index++;
			//cv_index = parseInt(table_data.component_data.table_component_ccg_list[class_var].display_order);
			table_data.lang_data.cv_list[class_var].cv_index = cv_index;
			table_data.cv_index_map[class_var] = cv_index;
			table_data.cv_map[cv_index] = table_data.lang_data.cv_list[class_var];
		}
		for (var ccg_index in temp_ccg_list) {
			var temp_cc_list = temp_ccg_list[ccg_index].cc_list;
			for (var class_code in temp_cc_list) {
				var cc_record = temp_cc_list[class_code];
				cc_record.class_var = class_var;
				cc_record.class_code_group = ccg_index;
				if (table_data.cc_index_map[class_var + "_" + class_code] === undefined) {
					cc_index++;
					cc_record.cc_index = cc_index;
					table_data.cc_index_map[class_var + "_" + class_code] = cc_index;
					table_data.cc_map[cc_index] = cc_record;
				}
			}
		}
	}
	sortCCYY(table_data);
	//sortCVs(table_data);
	var table_cv_list = [];
	for (var cv_value in table_data.cv_index_map) {
		table_cv_list.push(cv_value);
	}	
	// sv fields
	table_data.sv_map = [];
	table_data.sv_index_map = [];
	table_data.sp_map = [];
	table_data.sp_index_map = [];
	for (var stat_var in table_data.lang_data.sv_list) {
		var sv_record = table_data.lang_data.sv_list[stat_var];
		table_data.mdt_data[stat_var] = [];
		if (!all_mdt_list[stat_var]) {
			all_mdt_list[stat_var] = [];
		}
		sv_record.show = true;
		if (table_data.sv_index_map[stat_var] === undefined) {
			sv_index++;
			sv_record.sv_index = sv_index;
			table_data.sv_index_map[stat_var] = sv_index;
			table_data.sv_map[sv_index] = sv_record;
		}		
		// sp fields
		for (var stat_pres in sv_record.sp_list) {
			var sp_record = sv_record.sp_list[stat_pres];			
			if (table_data.sp_index_map[stat_var + "_" + stat_pres] === undefined) {
				sp_index++;
				sp_record.sp_index = sp_index;
				table_data.sp_index_map[stat_var + "_" + stat_pres] = sp_index;
				table_data.sp_map[sp_index] = sp_record;
				sp_record.show = true;
			}			
			// load MDT for this SV / SP
			var mdt_filename = getMdtFilename(table_data.theme_id, stat_var, stat_pres, table_data.table_id);	//use_table_mdt is removed, all MDT files in this section should contain table code
			var filepath = getMDT(dataDir, mdt_filename);
			table_data.mdt_load[filepath] = false;
			$.ajax({
				stat_var: stat_var,
				stat_pres: stat_pres,
				table_cv_list: table_cv_list,
				mdt_filename: mdt_filename,
				url: filepath,
				async: true,
				success: function (csvd) {
					var parse_csv_object = Papa.parse(csvd, { header: true, skipEmptyLines: true });
					var csv_object = parse_csv_object.data;
					// check if the mdt has any unused CV
					var mdt_record_list = getMdtListWithoutExtraCondition(csv_object, this.table_cv_list, table_data);					
					table_data.mdt_data[this.stat_var][this.stat_pres] = mdt_record_list.slice(0);
					if (!table_data.original_mdt_data) {
						table_data.original_mdt_data = [];
					}
					if (!table_data.original_mdt_data[this.stat_var]) {
						table_data.original_mdt_data[this.stat_var] = [];
					}
					table_data.original_mdt_data[this.stat_var][this.stat_pres] = mdt_record_list.slice(0);
					if (table_id_list.length > 1) {
						all_mdt_list[this.stat_var][this.stat_pres] = csv_object;
					} else {
						all_mdt_list[this.stat_var][this.stat_pres] = mdt_record_list;
					}				
					//check ccyy can exist without other time series
					var time_series_mdt_record_list = mdt_record_list.slice();
					for (var check_time_series_cv in table_data.lang_data.cv_list) {
						if (check_time_series_cv == CCYY) {
							continue;
						}
						var check_time_series_cv_record = table_data.lang_data.cv_list[check_time_series_cv];
						if (check_time_series_cv_record.is_time_series == '1') {
							time_series_mdt_record_list = $.grep(time_series_mdt_record_list, function (obj) { return (obj[check_time_series_cv] == '') || (!obj[check_time_series_cv]); });
						}
					}
					if (time_series_mdt_record_list.length > 0) {
						table_data.single_ccyy_allow = true;
					}
				},
				error: function (e) {
					table_data.missing_file = true;
					if (e && e.status === 403) {
						showNotFoundMsg(this.url, error_msg.forbidden);
					} else {
						showNotFoundMsg(this.url);
					}
					getTableListPage(table_data.table_id);
				},
				dataType: "text",
				complete: function () {
					if (table_data.missing_file) {
						return;
					}
					table_data.mdt_load[this.url] = true;
					loadMdtData(table_data);
					if (window.isWebReport) {
						var tid = "#" + table_data.table_id;
						var cols = $(tid + " thead tr:nth-child(3) th");
						var totalColumns = 0;
						if (cols && cols[0]) {
							for (var i = 0; i < cols.length; i++) {
								var colspan = $(cols[i]).attr("colspan");
								if (!colspan) {
									colspan = 1;
								}
								totalColumns += parseInt(colspan);
							}
							if (totalColumns <= 4) {
								$(tid)[0].classList.add("pivotTable" + (totalColumns - 1));
							}
						}
					}
				}
			});
		}		
		all_sv_list[stat_var] = table_data.lang_data.sv_list[stat_var];
	}	
	// sdmx schema
	table_data.xsd_load = false;
	table_data.sdmx_load = false;
	showDownloadXml(table_data);
	//addDuplicatedCC(table_data);
	initChart(table_data, dataDir);
	if (typeof cdm_text_file !== 'undefined' && table_resolve[cdm_text_file]) {
		table_resolve[cdm_text_file]({
			subject_code_list: [],
			table_data: null
		});
	}
}

function checkSdmxExists(table_data) {
	return table_data.component_data.schema_id && table_data.component_data.schema_id !== "0";
}

function loadSdmx(table_data) {
	if (checkSdmxExists(table_data)) {
		var dataDir = "/data/";
		if (window.isWebReport) {
			dataDir = web_element.dataURL;
		}
		var sdmx_xsd_filename = getCacheFile(dataDir + langDir + "sdmx_" + table_data.component_data.schema_id + "_lang.xsd");
		var sdmx_json_filename = getCacheFile(dataDir + langDir + "sdmx_" + table_data.component_data.schema_id + "_lang.json");
		var p1 = new Promise(function(resolve, reject) {
			$.ajax({
				url: sdmx_xsd_filename,
				async: true,
				success: function (xsd) {
					table_data.xsd = xsd;
					table_data.xsd_load = true;
				},
				error: function (e) {
					$("#download_sdmx").hide();
					errorLog("SDMX", "No XSD file found, please check the component file.");
				},
				dataType: "text",
				complete: function () {
					resolve();
				}
			});
		});
		var p2 = new Promise(function (resolve, reject) {
			$.getJSON(sdmx_json_filename, function (data) {
				table_data.sdmx_load = true;
				table_data.sdmx_data = data;
				//showDownloadXml(table_data);
				resolve();
			}).fail(function () {
				$("#download_sdmx").hide();
				errorLog("SDMX", "No SDMX file found, please check the component file.");
			});
		});
		return Promise.all([p1, p2]);
	} else {
		return Promise.all([]);
	}
}

function loadMdtData(table_data, reloadFlag) {
	for (var mtd_filename in table_data.mdt_load) {
		var loaded = table_data.mdt_load[mtd_filename];
		if (!loaded) {
			return;
		}
	}
	table_data.mdt_all_load = true;	
	var all_has_data = true;
	for (var mdt_index in all_mdt_list) {
		var check_data = all_mdt_list[mdt_index];
		if (check_length(check_data) == 0) {
			all_has_data = false;
		}
	}
	buildCdmTableUi(table_data, reloadFlag);
}

function buildEmptyColumnRowRecord() {
	return {
		is_cv: false,
		class_var: null,
		ccg_list: [],
		sv_sp_list: [],
		cell_list: [],
		permutate_cell_list: [],
		is_tv: false
	};
}

function buildCvColumnRowRecord(table_data, class_var, ccg_list) {
	var result = buildEmptyColumnRowRecord();
	result.is_cv = true;
	result.class_var = class_var;
	result.ccg_list = ccg_list;
	var cv = table_data.component_data.table_component_ccg_list[class_var];
	if (cv) {
		result.is_tv = table_data.lang_data.cv_list[class_var].is_time_series === "1";
		if (result.is_tv) {
			result.tv_display_seq = cv.tv_display_seq ? cv.tv_display_seq : cv.display_order;
		}
	}
	var pac = buildPacList(table_data, class_var);
	if (ccg_list.length > 1) {
		buildPacTree(table_data, pac, null, 0, result, true);
	} else {	//could be pac grid mode or normal cv		
		ccg_list.forEach(function (v) {
			var cnt = 0;
			var ccg = table_data.lang_data.cv_list[class_var].ccg_list[v.class_code_group];
			var cc_list = ccg.cc_list;
			var cc = null;
			var temp_pac = null;
			var hiddenCC = false;
			for (var class_code in cc_list) {
				/*if (!checkMdtExistsForRowColumnValues(table_data, class_var, class_code)){
					continue;
				}*/
				var flag = true;
				cc = cc_list[class_code];
				cc.class_var = class_var;
				cc.class_code_group = v.class_code_group;
				cc.class_code = class_code;
				cc.class_code_seq = parseInt(cc.class_code_seq);
				temp_pac = pac.filter(function (f) { return f.class_code_group === v.class_code_group && f.class_code === class_code; })[0];
				var parent_pac = pac.filter(function (f) { return f.class_code_group === cc.class_code_group && f.class_code === class_code })[0];
				var parent_id = parent_pac ? parent_pac.parent_id : null;
				var total_children = pac.filter(function (f) { return (parent_id ? f.parent_id === parent_id : !f.parent_id); }).length;
				if (temp_pac && temp_pac.marked && parent_id) {
					var p_node = pac.filter(function (f) { return f.id === parent_id; })[0];
					if (p_node) {
						flag = p_node.show || p_node.sv_show || p_node.sp_show;
					}
				}
				//if (cnt === 0 && v.cv_total_show === 1 && (total_children > 1 || !temp_pac || (temp_pac.children && temp_pac.children.length > 0))) {	//TIR016
				if (cnt === 0 && v.cv_total_show === 1 && (total_children > 0 || !temp_pac || (temp_pac.children && temp_pac.children.length > 0))) {
					var itm = createPACItem(table_data, temp_pac || cc, 0, true);
					itm.class_code_seq = -1;
					if (itm.show) {
						result.cell_list.push(itm);
					}
				}
				if (flag) {
					var cell_record = createPACItem(table_data, temp_pac || cc, 0);
					if (cell_record.show) {
						result.cell_list.push(cell_record);
						if (temp_pac) {
							cell_record.pac = buildPacTree(table_data, pac, temp_pac.children, 1, result, false, null, true);
						}
					} else {
						hiddenCC = true;
					}					
				}
				cnt += 1;
			}
			//if (v.cv_total_show === 2 && (result.cell_list.length > 1 || pac.length > 0 || hiddenCC)) {	//TIR016
			if (v.cv_total_show === 2 && (result.cell_list.length > 0 || pac.length > 0 || hiddenCC)) {	
				if (temp_pac || cc) {
					var itm = createPACItem(table_data, temp_pac || cc, 0, true);
					itm.class_code_seq = result.cell_list.length > 0 ? finMaxValue(result.cell_list, "class_code_seq") + 1 : 1;
					if (itm.show) {
						result.cell_list.push(itm);
					}
				}
			}
		});
		result.cell_list.sort(compareClassCodeSeq);
	}
	/*if (result && result.cell_list && result.cell_list.filter(function (v) { return v.show && !v.is_total; }).length <= 0) {
		result.cell_list.filter(function (v) { return v.show && v.is_total; }).forEach(function (v) {
			v.show = false;
		});
	}*/
	return result;
}

function buildSvColumnRowRecord(table_data, sv_sp_list) {
	var result = buildEmptyColumnRowRecord();
	result.is_cv = false;
	result.sv_sp_list = sv_sp_list;	
	for (var sv_sp_index in sv_sp_list) {
		var sv_sp_record = sv_sp_list[sv_sp_index];
		var sv_obj = table_data.lang_data.sv_list[sv_sp_record.stat_var];
		var sp_obj = sv_obj.sp_list[sv_sp_record.stat_pres];		
		if (sv_obj.show && sp_obj.show) {
			result.cell_list.push({
				is_sv: true,
				stat_var: sv_sp_record.stat_var,
				stat_pres: sv_sp_record.stat_pres,
				sv_text: sv_obj.def_stat_desc,
				sp_text: sp_obj.def_stat_pres_desc,
				indent: 0,
				children: [],
				pac: [],
				mdt_lookup_path: [],
				sv_show: sv_obj.show,
				sp_show: sp_obj.show
			});
		}
	}
	return result;
}

// if this cc has data, set the parent of this cc to has data recursively
function setParentHasData(cv_record, child_ccg, child_class_code) {	
	var cc_record = cv_record.ccg_list[child_ccg].cc_list[child_class_code];
	cc_record.has_data = true;
	cc_record.show = true;
	if (cc_record.parent_ccg && cc_record.parent_class_code) {
		setParentHasData(cv_record, cc_record.parent_ccg, cc_record.parent_class_code);
	}
}

function buildCdmTableUi(table_data, reloadFlag) {
	if (!table_data.mdt_all_load || !table_data.chart_all_load) {
		return;
	}
	var ccyy_list = {};
	var ccyy_f_list = {};	
	for (var class_var in table_data.component_data.table_component_ccg_list) {
		var cv_record = table_data.component_data.table_component_ccg_list[class_var];
		if ((table_data.lang_data.cv_list[class_var].is_time_series != '1') || (table_data.time_series_counter > 2)) {
			var temp_ccg_list = cv_record.ccg_list;
			for (var ccg_index in temp_ccg_list) {
				var itm = table_data.component_data.table_component_ccg_list[class_var].ccg_list[ccg_index];
				if (typeof(itm.cv_total_show) == 'undefined') {
					itm.cv_total_show = parseInt(itm.show_total);
				}
			}
		}
	}
	// check cv / cc has data
	for (var cv_index in table_data.lang_data.cv_list) {		
		var temp_ccg_list = table_data.lang_data.cv_list[cv_index].ccg_list;
		for (var ccg_index in temp_ccg_list) {			
			var temp_cc_list = temp_ccg_list[ccg_index].cc_list;
			for (var cc_index in temp_cc_list) {
				var cc_record = temp_cc_list[cc_index];
				var has_data = false;				
				sv_loop:
				for (var mdt_sv_index in table_data.mdt_data) {
					var mdt_sv = table_data.mdt_data[mdt_sv_index];					
					sp_loop:
					for (var mdt_sp_index in mdt_sv) {
						var mdt_sp = mdt_sv[mdt_sp_index];
						mdt_sp = $.grep(mdt_sp, function (obj) { return (obj[cv_index] == cc_index); });
						if (mdt_sp.length > 0) {
							has_data = true;
							break sv_loop;
						}
					}
				}				
				cc_record.has_data = has_data;
				cc_record.show = has_data;
				if (!full_series && cc_record.default_hide == '1') {
					cc_record.show = false;
				}				
				if (has_data) {
					if (cv_index == CCYY) {
						ccyy_list[cc_index] = cc_record;
					}
					if (cv_index == CCYY_F) {
						ccyy_f_list[cc_index] = cc_record;
					}
				}
			}
		}		
		// set the pac relationship for has data
		var pac_list = table_data.lang_data.cv_list[cv_index].pac_list;
		pac_list.sort(compareDisplayOrder);
		var cc_record_list = [];
		for (var pac_i in pac_list) {
			var pac_record = pac_list[pac_i];
			var parent_ccg = pac_record.parent_class_code_group;
			var child_ccg = pac_record.child_class_code_group;
			var parent_class_code = pac_record.parent_class_code;
			var child_class_code = pac_record.child_class_code;			
			table_data.lang_data.cv_list[cv_index].ccg_list[child_ccg].cc_list[child_class_code].parent_ccg = parent_ccg;
			table_data.lang_data.cv_list[cv_index].ccg_list[child_ccg].cc_list[child_class_code].parent_class_code = parent_class_code;
		}
		// after the pac tree is built, loop again
		for (var pac_i in pac_list) {
			var pac_record = pac_list[pac_i];
			var parent_ccg = pac_record.parent_class_code_group;
			var child_ccg = pac_record.child_class_code_group;
			var parent_class_code = pac_record.parent_class_code;
			var child_class_code = pac_record.child_class_code;
			if (table_data.lang_data.cv_list[cv_index].ccg_list[child_ccg].cc_list[child_class_code].has_data &&
				table_data.lang_data.cv_list[cv_index].ccg_list[child_ccg].cc_list[child_class_code].show) {
				setParentHasData(table_data.lang_data.cv_list[cv_index], parent_ccg, parent_class_code);
			}
		}
		// set the default show latest record
		if (table_data.component_data.default_series_period && indenpendent_tv_list.includes(cv_index)) {
			var default_series_period = parseInt(table_data.component_data.default_series_period);
			for (var ccg_index in temp_ccg_list) {
				var temp_cc_list = temp_ccg_list[ccg_index].cc_list;
				var filtered_cc_list = [];
				for (var cc_index in temp_cc_list) {
					var cc_record = temp_cc_list[cc_index];
					if (cc_record.has_data) {
						filtered_cc_list.push(cc_record);
					}
				}
				filtered_cc_list.sort(compareClassCodeSeq);				
				if (!full_series) {
					for (var z = 0; z < filtered_cc_list.length - default_series_period; z++) {
						var cc_record = filtered_cc_list[z];
						cc_record.show = false;
					}
				}
			}
		}
	}
	table_data.ccyy_list = ccyy_list;
	table_data.ccyy_f_list = ccyy_f_list;
	// build a selectable time series list
	table_data.ccyy_time_series_list = {};
	table_data.ccyy_time_series_map = {};
	var has_ccyy_only_time_series = false;
	var full_time_series_list = [];
	var full_years = [];
	var max_year = findMaxYear(table_data);			
	if (check_length(ccyy_list) > 0) {
		for (var ccyy_index in ccyy_list) {
			var ccyy_record = ccyy_list[ccyy_index];			
			for (var class_var in table_data.lang_data.cv_list) {				
				var cv_record = table_data.lang_data.cv_list[class_var];
				if (cv_record.is_time_series === "1") {
					if (!table_data.ccyy_time_series_list[class_var]) {
						table_data.ccyy_time_series_list[class_var] = [];
					}
					if (!table_data.ccyy_time_series_map[class_var]) {
						table_data.ccyy_time_series_map[class_var] = {};
					}
					if (!full_time_series_list[class_var]) {
						full_time_series_list[class_var] = [];
					}
					var temp_ccg_list = cv_record.ccg_list;
					for (var ccg_index in temp_ccg_list) {
						var temp_cc_list = temp_ccg_list[ccg_index].cc_list;
						for (var cc_index in temp_cc_list) {
							var cc_record = temp_cc_list[cc_index];
							var has_data = false;							
							if (!indenpendent_tv_list.includes(class_var)) {
								sv_loop:
								for (var mdt_sv_index in table_data.mdt_data) {
									var mdt_sv = table_data.mdt_data[mdt_sv_index];									
									sp_loop:
									for (var mdt_sp_index in mdt_sv) {
										var mdt_sp = mdt_sv[mdt_sp_index];									
										if (!has_ccyy_only_time_series) {
											// check if it has CCYY only time series
											var ccyy_mdt_sp = $.grep(mdt_sp, function (obj) { return (obj[class_var] == '') && (obj[CCYY] == ccyy_index); });
											if (ccyy_mdt_sp.length > 0) {
												has_ccyy_only_time_series = true;
												break sv_loop;
											}
										}
									}
								}
								sv_loop:
								for (var mdt_sv_index in table_data.mdt_data) {
									var mdt_sv = table_data.mdt_data[mdt_sv_index];									
									sp_loop:
									for (var mdt_sp_index in mdt_sv) {
										var mdt_sp = mdt_sv[mdt_sp_index];										
										mdt_sp = $.grep(mdt_sp, function (obj) { return (obj[class_var] == cc_index) && (obj[CCYY] == ccyy_index); });
										if (mdt_sp.length > 0) {
											has_data = true;
											break sv_loop;
										}
									}
								}
							} else {
								sv_loop:
								for (var mdt_sv_index in table_data.mdt_data) {
									var mdt_sv = table_data.mdt_data[mdt_sv_index];									
									sp_loop:
									for (var mdt_sp_index in mdt_sv) {
										var mdt_sp = mdt_sv[mdt_sp_index];
										for (var cv in table_data.lang_data.cv_list) {
											var cv_r = table_data.lang_data.cv_list[cv];
											if (cv_r.is_time_series === "1") {
												if (cv !== class_var) {
													mdt_sp = mdt_sp.filter(function (v) { return !v[cv]; });
												} else {
													mdt_sp = mdt_sp.filter(function (v) { 
														return v[class_var] === (cv === CCYY ? ccyy_index : cc_index);
													});
												}
											}
										}
										if (mdt_sp.length > 0) {
											has_data = true;
											break sv_loop;
										}
									}
								}
							}
							if (has_data) {
								var ccyy_time_series_record = {
									ccyy_index: ccyy_index,
									ccyy_record: ccyy_record,
									time_series_index: cc_index,
									time_series_record: cc_record,
									show: (ccyy_record.show && cc_record.show)
								};						
								table_data.ccyy_time_series_list[class_var].push(ccyy_time_series_record);
								if (!table_data.ccyy_time_series_map[class_var][ccyy_index]) {
									table_data.ccyy_time_series_map[class_var][ccyy_index] = {};
								}
								if (!indenpendent_tv_list.includes(class_var)) {
									table_data.ccyy_time_series_map[class_var][ccyy_index][cc_index] = ccyy_time_series_record;
									if (parseInt(ccyy_index) < max_year) {										
										full_time_series_list[class_var][ccyy_index] = true;
										if (!full_years.includes(ccyy_index)) {
											full_years.push(ccyy_index);
										}
									} else {
										var max_node = latest_tv_list.filter(function (v) { return v.class_var === class_var && v.max === cc_index; })[0];
										if (max_node) {										
											full_time_series_list[class_var][ccyy_index] = true;
											if (!full_years.includes(ccyy_index)) {
												full_years.push(ccyy_index);
											}
										}
									}
								} else if (class_var === CCYY_F) {
									//table_data.ccyy_time_series_map[class_var][cc_index] = ccyy_time_series_record;
									full_time_series_list[class_var][cc_index] = true;
									if (!full_years.includes(cc_index)) {
										full_years.push(cc_index);
									}
								} else {
									full_time_series_list[class_var][ccyy_index] = true;
									if (!full_years.includes(ccyy_index)) {
										full_years.push(ccyy_index);
									}
								}
							}
						}
					}
				}
			}
		}		
	}
	full_years = full_years.sort(function (a, b) { if (a < b) { return 1; } else { return -1; } }).slice(0, default_series_period);
	table_data.ccyy_time_series_map_done = true;
	// update default_series_period
	if (table_data.component_data.table_component_ccg_list[CCYY] && 
		table_data.component_data.default_series_period && has_ccyy_only_time_series) {
		var default_series_period = parseInt(table_data.component_data.default_series_period);
		for (var class_var in full_time_series_list) {
			var number_of_records_show = check_length(full_time_series_list[class_var]);
			if (number_of_records_show >= default_series_period) {
				var will_show = full_series || false;
				for (var ccyy_index in full_time_series_list[class_var]) {
					if (full_time_series_list[class_var][ccyy_index]) {
						var ccyy_record = ccyy_list[ccyy_index];
						var flg = will_show || full_years.includes(ccyy_index);
						ccyy_record.show = flg;
						for (var cc_index in table_data.ccyy_time_series_map[class_var][ccyy_index]) {
							var ccyy_time_series_record = table_data.ccyy_time_series_map[class_var][ccyy_index][cc_index];
							ccyy_time_series_record.show = flg;
						}
						delete full_time_series_list[class_var][ccyy_index];
					}
				}
			}
		}
	}
	if (!reloadFlag) {
		var flg = typeof (cdm_text_file) === 'undefined';
		if (!window.isWebReport && !window.isPic) {
			buildSvSpCheckBox(table_data);
			buildCvCheckBox(table_data);
			if ((typeof(idds) != 'undefined') && (idds)) {
				generateCurrentSelectionUrl(table_data);
			} else if (flg) {
				setTableDataFromUrl(table_data);
			}
			//generateCurrentSelectionJson(table_data);
			setUiComponent(table_data);
		}
		if (typeof default_demographics_lookup_path !== 'undefined') {
			buildMapCombobox();
		} else {
			if (flg && $("#submitButton")[0]) {
				//escapeAccessLog = true;
				/*if (!table_data.component_data.schema_id || table_data.component_data.schema_id === "0") {
					$("#submitButton").click();
				} else {
					var interval = null;
					interval = setInterval(function () {
						if (table_data.sdmx_load) {
							clearInterval(interval);
							$("#submitButton").click();
						}
					}, 100);
				}*/
				$("#submitButton").click();
			} else {
				buildCdmTable(table_data, (table_id_list.length > 0));
			}
		}
	}
}

function findMaxYear(table_data) {
	var max_year = 0;
	for (var mdt_sv_index in table_data.mdt_data) {
		var mdt_sv = table_data.mdt_data[mdt_sv_index];
		for (var mdt_sp_index in mdt_sv) {
			max_year = Math.max(finMaxValue(mdt_sv[mdt_sp_index], ["CCYY", "CCYY_F"]), max_year);
		}
	}
	return max_year;
}

function getCcgArrayIndex(ccg_list, ccg) {
	for (var index in ccg_list) {
		var ccg_record = ccg_list[index];
		if (ccg_record.class_code_group == ccg) {
			return index;
		}
	}
	return -1;
}

function addSVCVNotes(record, note_text, idx, i) {
	if (!record.notes) {
		record.notes = [];
	}
	var note = record.notes.filter(function (v) { return v.note_idx === i; })[0];
	if (!note) {
		record.notes.push({	
			note: note_text,
			symbol: idx,
			note_idx: i
		});
	} else {
		note.symbol = idx;
	}
}

function createFootnote(record, html_text, footnote_used_list, table_data) {	
	var add_table_id_to_sd_symbol = false;
	var table_order = null;
	if (table_data) {
		var table_notes_element = document.getElementById(table_data.table_id + '_' + table_notes);
		if (table_notes_element) {
			add_table_id_to_sd_symbol = true;
			table_order = getTableListOrder(table_data.table_id) + 1;
			table_notes_element.innerHTML = "";
		}
	}
	// check if the record is null, eg total is null
	var notes = [];
	if (record) {		
		var record_used_index_list = [];
		for (var i = 1; i <= 10; i++) {
			//var note_value = eval('record.note' + i);
			var note_value = record['note' + i];
			if (note_value) {				
				// check if the footnote already exist in the list
				var footnote_index = footnote_used_list.indexOf(note_value);
				if (footnote_index < 0) {
					footnote_used_list.push(note_value);					
					// get the max footnotes counter
					footnote_index = footnote_used_list.length;
				} else {
					// since array start from 0, need to add 1 
					footnote_index = footnote_index + 1;
				}
				addSVCVNotes(record, note_value, footnote_index, i);
				var check_record_used_index = record_used_index_list.indexOf(footnote_index);
				if (check_record_used_index < 0) {
					record_used_index_list.push(footnote_index);
					if (add_table_id_to_sd_symbol && table_order) {
						var table_order_footnote_index = table_data.table_id + '_' + footnote_index;
						var table_order_footnote_index_obj;
						var table_order_footnote_index_id = 'cdm_footnote_' + table_order_footnote_index_id_counter;
						if (table_order_footnote_index_map[table_order_footnote_index]) {
							table_order_footnote_index_obj = table_order_footnote_index_map[table_order_footnote_index];
						} else {
							table_order_footnote_index_obj = {
								table_order_footnote_index_id: [],
								table_order_footnote_index_number: table_order_footnote_index_id_counter,
								table_order_footnote_index_text: null
							};
						}
						table_order_footnote_index_obj.table_order_footnote_index_id.push(table_order_footnote_index_id);
						table_order_footnote_index_map[table_order_footnote_index] = table_order_footnote_index_obj;
						table_order_footnote_index_id_counter++;
						notes.push(footnote_index);
					} else {
						notes.push(footnote_index);
					}
				}
			}
		}
	}
	if (notes && notes.length > 0) {
		notes = notes.sort(function (a, b) { 
			if (parseInt(a) < parseInt(b)) { 
				return -1; 
			} else { 
				return 1; 
			} 
		});
		notes.forEach(function (v) {
			html_text += ' <a href="#' + (table_data ? table_data.table_id + "_" : "") + v.toString() + '" class="cdm_footnote">(' + v.toString() + ')</a>';
		});
	}
	return html_text;
}

function getCC(table_data, class_var, class_code) {
	var ccg_list = table_data.lang_data.cv_list[class_var].ccg_list;
	for (var ccg_index in ccg_list) {
		var ccg_record = ccg_list[ccg_index];
		if (ccg_record.cc_list[class_code]) {
			return ccg_record.cc_list[class_code];
		}
	}
	return null;
}

function setTableTitle(table_data, update_website_title) {
	var table_title_string = ds_title.table + table_data.table_id + ds_title.symbol + table_data.lang_data.tb_title;
	if (!window.isWebReport && update_website_title && !window.isPic) {
		var table_title_element = document.getElementById('w_content');
		if (table_title_element) {
			table_title_element.innerHTML = table_title_string;
			$("#w_content").show();
		}		
		if (table_id_list.length == 1) {
			document.title = htmlDecode(table_title_string);
		}
	}
	table_data.table_title_string = table_title_string;
}

function checkLookupContainsCCYYTVonly(table_data, mdt_lookup_path, record) {
	var result = "";
	var tvs = mdt_lookup_path.filter(function (v) {
		return table_data.lang_data.cv_list[v.class_var] && table_data.lang_data.cv_list[v.class_var].is_time_series === "1";
	}).map(function (v) {
		return v.class_var;
	});
	if (tvs && tvs.length > 0) {
		if (tvs.length === 1 && tvs[0] === CCYY) {
			result = CCYY;
			if (record) {
				if (record.class_var === CCYY) {
					var children = record.children;
					if (children && children.length > 0) {
						var cv = children[0].class_var;
						if (table_data.lang_data.cv_list[cv] && table_data.lang_data.cv_list[cv].is_time_series === "1") {
							result = cv;
						}
					}
				}
			}
		} else if (tvs.length > 1) {
			var tv = tvs.filter(function (v) {
				return !(indenpendent_tv_list.concat(no_ccyy_tv).includes(v));
			})[0];
			if (tv) {
				result = tv;
			}
		}
	}
	if (result) {
		result = "_" + result;
	}
	return result;
}

function formatCellId(table_data, ids) {
	var result = "";
	if (ids && ids.length > 0) {
		ids.forEach(function (id) {
			while (id.endsWith("_")) {
				id = id.substring(0, id.length - 1);
			}
			result += (window.isWebReport ? (table_data.table_id ? table_data.table_id + "_" : "") : "") + id + " ";
		});	
	}
	return result.trim();
}

function setCellId(table_data, record, cell) {
	var cell_id = '';
	var cell_header_attribute = '';
	if (record.mdt_lookup_path) {
		var ccyy_suffix = checkLookupContainsCCYYTVonly(table_data, record.mdt_lookup_path, record);
		var mdt_lookup_path_length = record.mdt_lookup_path.length;
		if (mdt_lookup_path_length > 0) {
			var previous_id = '';
			for (var looup_record_index = 0; looup_record_index < mdt_lookup_path_length; looup_record_index++) {
				var v = record.mdt_lookup_path[looup_record_index];
				if (v) {
					var record_cell_id = '';					
					if (looup_record_index == mdt_lookup_path_length - 1) {
						if (v.is_sv) {
							var sv_id = 'sv_' + replaceStringSpace(v.stat_var);
							if (record.is_sv) {
								record_cell_id = sv_id;
							} else if (record.is_sp) {
								record_cell_id = sv_id + '_sp_' + replaceStringSpace(v.stat_pres);
								cell_header_attribute += sv_id;
							}
						} else {
							record_cell_id = 'cv_' + v.class_var + '_cc_' + v.class_code + (v.class_var === CCYY ? ccyy_suffix : "");
							if (v.special_ccyy) {
								record_cell_id += '_special_ccyy';
							}
							var cv_desc = table_data.lang_data.cv_list[record.class_var].def_class_desc;
							var used_cv_desc = cv_desc;
							var ccg_desc = null;
							if (!Array.isArray(record.class_code_group)) {
								ccg_desc = table_data.lang_data.cv_list[record.class_var].ccg_list[record.class_code_group].ccg_desc;
							}
							if (ccg_desc != null) {
								if (((typeof(idds) != 'undefined') && (idds)) || ((typeof(census21) != 'undefined') && (census21))) {
									// no need to use ccg description for 21C
								} else {
									used_cv_desc = ccg_desc;
								}
							}
							cell_header_attribute += 'cv_' + replaceStringSpace(used_cv_desc);
							cell_header_attribute += ' ';
						}
						cell_id += record_cell_id;
					} else {
						if (v.is_sv) {
							var record_cell_id_1 = 'sv_' + replaceStringSpace(v.stat_var);
							var record_cell_id_2 = 'sv_' + replaceStringSpace(v.stat_var) + '_sp_' + replaceStringSpace(v.stat_pres);
							if (previous_id) {
								previous_id = previous_id + '_' + record_cell_id_2;
								cell_header_attribute += previous_id + '_' + record_cell_id_1;
								cell_header_attribute += ' ';
								cell_header_attribute += previous_id + '_' + record_cell_id_2;
							} else {
								previous_id = record_cell_id_2;
								cell_header_attribute += record_cell_id_1;
								cell_header_attribute += ' ';
								cell_header_attribute += record_cell_id_2;
							}
							cell_id += record_cell_id_2;
						} else {
							record_cell_id = 'cv_' + v.class_var + '_cc_' + v.class_code + (v.class_var === CCYY ? ccyy_suffix : "");
							if (v.special_ccyy) {
								record_cell_id += '_special_ccyy';
							}
							if (previous_id) {
								cell_header_attribute += previous_id + '_' + record_cell_id;
								previous_id = previous_id + '_' + record_cell_id;
							} else {
								cell_header_attribute += record_cell_id;
								previous_id = record_cell_id;
							}
							cell_id += record_cell_id;
						}
						cell_header_attribute += ' ';
						cell_id += '_';
					}
				}
			}
		}
	} else {
		cell_id = 'cv_' + replaceStringSpace(record);
	}	
	if (cell_id) {
		cell.id = formatCellId(table_data, [cell_id]);
	}
	if (cell_header_attribute) {
		cell.setAttribute("headers",  formatCellId(table_data, cell_header_attribute.trim().split(" ")));
	}
}

function setMdtCellHeaders(table_data, row_record, column_mdt_lookup_path, cell) {
	var cell_header_attribute = '';
	cell_header_attribute = buildCellHeaderAttribute(table_data, cell_header_attribute, column_mdt_lookup_path);
	cell_header_attribute = buildCellHeaderAttribute(table_data, cell_header_attribute, row_record.mdt_lookup_path);
	if (cell_header_attribute) {
		cell.setAttribute("headers",  formatCellId(table_data, cell_header_attribute.trim().split(" ")));
	}
}

function buildCellHeaderAttribute(table_data, cell_header_attribute, mdt_lookup_path) {
	if (mdt_lookup_path) {
		var ccyy_suffix = checkLookupContainsCCYYTVonly(table_data, mdt_lookup_path);
		var mdt_lookup_path_length = mdt_lookup_path.length;
		if (mdt_lookup_path_length > 0) {
			var previous_id = '';
			for (var looup_record_index = 0; looup_record_index < mdt_lookup_path_length; looup_record_index++) {
				var v = mdt_lookup_path[looup_record_index];
				if (v) {
					var record_cell_id = '';					
					if (v.is_sv) {
						var record_cell_id_1 = 'sv_' + replaceStringSpace(v.stat_var);
						var record_cell_id_2 = 'sv_' + replaceStringSpace(v.stat_var) + '_sp_' + replaceStringSpace(v.stat_pres);
						if (previous_id) {
							previous_id = previous_id + '_' + record_cell_id_2;
							cell_header_attribute += previous_id + '_' + record_cell_id_1;
							cell_header_attribute += ' ';
							cell_header_attribute += previous_id + '_' + record_cell_id_2;
						} else {
							previous_id = record_cell_id_2;
							cell_header_attribute += record_cell_id_1;
							cell_header_attribute += ' ';
							cell_header_attribute += record_cell_id_2;
						}
					} else {
						record_cell_id = 'cv_' + v.class_var + '_cc_' + v.class_code + (v.class_var === CCYY ? ccyy_suffix : "");
						if (v.special_ccyy) {
							record_cell_id += '_special_ccyy';
						}
						if (previous_id) {
							cell_header_attribute += previous_id + '_' + record_cell_id;
							previous_id = previous_id + '_' + record_cell_id;
						} else {
							cell_header_attribute += record_cell_id;
							previous_id = record_cell_id;
						}
					}
					cell_header_attribute += ' ';
				}
			}
		}
	}
	return cell_header_attribute;
}

function buildColumnRowTreeByCheckingFirstItem(table_data, column_row_array, depth_obj) {
	var result = [];
	var nexts = [0];
	if (column_row_array && column_row_array.length > 0) {
		var first = column_row_array[0];
		if (first.is_tv) {
			column_row_array.filter(function (v) { return indenpendent_tv_list.includes(v.class_var) && v.class_var !== first.class_var; }).forEach(function (v) {
				nexts.push(column_row_array.indexOf(v));
			});
		}
		nexts.forEach(function (v) {
			result = result.concat(buildColumnRowTree(table_data, column_row_array, v, [], depth_obj, table_data.mdt_data));
		});
		result = orderingColumnRowTreeChildren(nexts, result, column_row_array);
	}
	return result;
}

function filterSVMDT(table_data, s) {
	s.mdt = table_data.original_mdt_data[s.stat_var][s.stat_pres].slice(0);
	var cv = {
		class_var: CCYY,
		class_code_group: ""
	}
	var years = objectToList(table_data.ccyy_list);
	var temp = [];
	if (years && years.length > 0) {
		cv.class_var = years[0].class_var;
		cv.class_code_group = years[0].class_code_group;
		years = objectToList(table_data.lang_data.cv_list[cv.class_var].ccg_list[cv.class_code_group].cc_list);
		var yrs = years.filter(function (f) { return f.show; });
		if (yrs.length < years.length) {		
			yrs.forEach(function (y) {
				temp = temp.concat(s.mdt.filter(function (f) { return f[y.class_var] === y.class_code; }));
			});
		} else {
			temp = temp.concat(s.mdt.filter(function (f) { return f[cv.class_var]; }).slice(0));
		}
	}
	years = objectToList(table_data.ccyy_f_list);
	if (years && years.length > 0) {
		cv.class_var = years[0].class_var;
		cv.class_code_group = years[0].class_code_group;
		years = objectToList(table_data.lang_data.cv_list[cv.class_var].ccg_list[cv.class_code_group].cc_list);
		var yrs = years.filter(function (f) { return f.show; });
		if (yrs.length < years.length) {		
			yrs.forEach(function (y) {
				temp = temp.concat(s.mdt.filter(function (f) { return f[y.class_var] === y.class_code; }));
			});
		} else {
			temp = temp.concat(s.mdt.filter(function (f) { return f[cv.class_var]; }).slice(0));
		}
	}
	s.mdt = temp.slice(0);
	table_data.mdt_data[s.stat_var][s.stat_pres] = temp.slice(0);
	s.mdt.forEach(function (m) { 
		m.ignore_sd_values = [];
	});
}

function buildCdmTable(table_data, keep_note, skip_table) {
	table_data.time = {};
	table_data.time.start_time = new Date();
	if (window.isWebReport && !skip_table) {
		var seq = $("#table_name_" + table_data.table_id).closest(".tab-content").data("seq");
		$("#table_cap_" + table_data.table_id).html(ds_title.table + seq + ds_title.symbol + table_data.lang_data.tb_title);
	}
	cacheMdtData = [];
	var row_array = [];
	var column_array = [];	
	var footnote_used_list = [];
	var column_mdt_lookup_path = [];
	if (!skip_table) {
		mdt_counter[table_data.table_id] = 0;
		mdt_counter_map[table_data.table_id] = [];
		cc_counter[table_data.table_id] = 0;
		cc_counter_map[table_data.table_id] = [];	
	}
	// sort the CV display order
	var cv_order_list = [];
	for (var cv_name in table_data.component_data.table_component_ccg_list) {
		var cv_comp = table_data.component_data.table_component_ccg_list[cv_name];
		cv_comp.class_var = cv_name;
		cv_order_list.push(cv_comp);
	}
	cv_order_list.sort(compareDisplayOrder);
	// build the rows and columns for CV
	for (var cv_index in cv_order_list) {
		var cv_comp = cv_order_list[cv_index];
		if (cv_comp.ccg_list.length == 1) {	// simple case					
			var column_row_record = buildCvColumnRowRecord(table_data, cv_comp.class_var, cv_comp.ccg_list);
			if (cv_comp.cv_position == ROW) {
				row_array.push(column_row_record);
			} else {	// else column				
				column_array.push(column_row_record);
			}
		} else { // else parent and child case
			// sort the parent and child relatinship
			var pac_list = table_data.lang_data.cv_list[cv_comp.class_var].pac_list;
			for (var pac_i in pac_list) {
				var pac_record = pac_list[pac_i];
				var parent_ccg = pac_record.parent_class_code_group;
				var child_ccg = pac_record.child_class_code_group;				
				var p_index = getCcgArrayIndex(cv_comp.ccg_list, parent_ccg);
				var c_index = getCcgArrayIndex(cv_comp.ccg_list, child_ccg);				
				// move the child to the back, parent to the front
				if ((p_index >= 0) && (c_index >= 0) && (c_index < p_index)) {
					var temp_ccg_record = cv_comp.ccg_list[p_index];
					cv_comp.ccg_list[p_index] = cv_comp.ccg_list[c_index];
					cv_comp.ccg_list[c_index] = temp_ccg_record;
				}
			}			
			if ((cv_comp.cv_position == ROW) && (table_data.component_data.pac_mode == TOP)) {
				// build the CV in a single column header
				var column_row_record = buildCvColumnRowRecord(table_data, cv_comp.class_var, cv_comp.ccg_list);
				if (cv_comp.cv_position == ROW) {
					row_array.push(column_row_record);
				} else {
					column_array.push(column_row_record);
				}
			} else { // else bottom
				// build the CV in separate column header
				for (var ccg_var in cv_comp.ccg_list) {
					var column_row_record = buildCvColumnRowRecord(table_data, cv_comp.class_var, [cv_comp.ccg_list[ccg_var]]);
					if (cv_comp.cv_position == ROW) {
						row_array.push(column_row_record);
					} else {
						column_array.push(column_row_record);
					}
				}
			}
		}
	}
	// sort the SV display order
	table_data.component_data.table_component_list.sort(compareDisplayOrder);
	// build the rows and columns for SV
	var column_row_record = buildSvColumnRowRecord(table_data, table_data.component_data.table_component_list);
	switch (parseInt(table_data.component_data.sv_position)) {
		case ROW_LEFT: 
			row_array.unshift(column_row_record);
			break;
		case ROW_RIGHT: 
			row_array.push(column_row_record);
			break;
		case COLUMN_TOP: 
			column_array.unshift(column_row_record);
			break;
		case COLUMN_BOTTOM: 
		default:
			column_array.push(column_row_record);
			break;
	}
	showHidePacTotal(row_array.map(function (v) { return v.class_var} ));
	table_data.time.row_column_array_time = new Date();
	table_data.time.row_column_array_cost = table_data.time.row_column_array_time - table_data.time.start_time;
	var table_id = table_data.table_id;
	var html_table = document.getElementById(table_id);
	var html_concepts_methods_header = document.getElementById('conceptsMethods_header');
	var html_concepts_methods = document.getElementById('conceptsMethods');	
	if (!html_table) {
		html_table = document.getElementById(DEFAULT_TABLE);
	}
	if (!skip_table) {
		if (html_table && !window.isWebReport) {
			html_table.classList.add("pivotTable");
		}
		if (html_table) {
			$(html_table).css("margin", "");
			var title = $("#table_cap_" + table_data.table_id)[0];
			if (!window.isWebReport) {
				if (title) {
					$(html_table).attr("summary", $(title).html());
				} else {
					if (table_data.table_title_string) {
						$(html_table).attr("summary", table_data.table_title_string);
					} else {
						$(html_table).attr("summary", ds_title.table + table_data.table_id);
					}
				}
			}
			if (window.isWebReport) {
				var caption = $(html_table).children("caption")[0];
				if (caption) {
					html_table.innerHTML = caption.outerHTML + "<thead></thead><tbody></tbody>";
				} else {
					html_table.innerHTML = "<thead></thead><tbody></tbody>";
				}
			} else {
				html_table.innerHTML = "<thead></thead><tbody></tbody>";
			}
			setTableCaptionStyle();
		} else { // no ui element for this table
			if (table_resolve[table_id]) {
				table_resolve[table_id]({
					subject_code_list: [],
					table_data: table_data
				});
			}
			return;
		}
	}
	// permutate the cell list
	var sv_list = [];
	var sv_node = row_array.concat(column_array).filter(function (v) { return !v.is_cv || v.is_sv; })[0];
	if (sv_node) {
		sv_list = sv_node.sv_sp_list;
	}
	sv_list.forEach(function (s) {
		filterSVMDT(table_data, s);	//speed up filtering to remove null cells
	});
	table_data.time.sv_time = new Date(); 
	table_data.time.sv_cost = table_data.time.sv_time - table_data.time.row_column_array_time;
	var row_depth_obj = {
		depth: 0,
		has_sv: false,
		column_row_array: row_array
	};
	var row_cell_list = buildColumnRowTreeByCheckingFirstItem(table_data, row_array, row_depth_obj);
	var all_rows = getLeafNodes(row_cell_list, 1, true);
	table_data.time.row_time = new Date(); 
	table_data.time.row_cost = table_data.time.row_time - table_data.time.sv_time;
	var col_depth_obj = {
		depth: 0,
		has_sv: false,
		column_row_array: column_array
	};
	var column_cell_list = buildColumnRowTreeByCheckingFirstItem(table_data, column_array, col_depth_obj);
	var all_columns = getLeafNodes(column_cell_list, 1, false);
	table_data.time.column_time = new Date(); 
	table_data.time.column_cost = table_data.time.column_time - table_data.time.row_time;
	var all_cvs = objectToList(table_data.component_data.table_component_ccg_list).map(function (v) { return v.class_var; });	
	row_cell_list = checkMdtExistsAfterColumnRowArrayBuilt(all_cvs, row_cell_list, all_columns.filter(function (v) { return v.is_leaf; }), sv_list, row_array, false, true);
	//clearTempIgnoreSDValues(sv_list);
	column_cell_list = checkMdtExistsAfterColumnRowArrayBuilt(all_cvs, column_cell_list, all_rows.filter(function (v) { return v.is_leaf; }), sv_list, column_array, false, true);
	groupSDValues(table_data, all_cvs, sv_list, all_rows, all_columns);
	//clearTempIgnoreSDValues(sv_list);
	table_data.all_heads = all_rows.concat(all_columns);	//for building selection URL, null value headers are required
	if (skip_table) {
		table_data.all_heads_for_chart = all_rows.filter(function (f) { return f.show || f.sv_show || f.sp_show; }).concat(all_columns.filter(function (f) { return f.show || f.sv_show || f.sp_show ; }));
		return;
	}
	table_data_list[table_data.table_id] = table_data;
	var no_data = all_rows.filter(function (v) { return v.is_leaf && (v.show || v.sv_show || v.sp_show); }).length === 0 || all_columns.filter(function (v) { return v.is_leaf && (v.show || v.sv_show || v.sp_show); }).length === 0;
	if (no_data) {
		$(html_table).find("tbody").append("<tr><td><span style='font-size: 16px;'>" + error_msg.no_data + "</span></td></tr>");
		$(html_table).css("margin", "0");
		hideLoadingById("t", table_data.table_id);
		if (!window.isWebReport) {	//return cannot print web report
			return;
		}
	}
	table_data.time.remove_empty_cell_time = new Date(); 
	table_data.time.remove_empty_cell_cost = table_data.time.remove_empty_cell_time - table_data.time.column_time;
	// since sv / sp will create 2 cells; increment depth
	if (row_depth_obj.has_sv) {
		row_depth_obj.depth++;
	}
	if (col_depth_obj.has_sv) {
		col_depth_obj.depth++;
	}
	if (window.isWebReport && table_data.component_data.hide_table === "1") {
		var btn = $("a[href='#chart_" + table_data.table_id + "']")[0];
		if (btn) {
			btn.click();
			$("#ul_" + table_data.table_id).remove();
		} else {
			alert(error_msg.no_chart_hide_table.replace("[TABLE]", table_data.table_id));
		}
		$("#table_" + table_data.table_id).addClass("hide_table");
		if (!web_element.exclude_table_id.includes(table_data.table_id)) {
			web_element.exclude_table_id.push(table_data.table_id);
		}
		console.log(table_data.table_id + " is hidden");
	}
	// build the UI
	if (html_concepts_methods && html_concepts_methods_header) {
		var concept_count = 0;
		for (var concept_i = 1; concept_i <= 20; concept_i++) {
			if ((table_data.lang_data['cam' + concept_i + '_title']) && (table_data.lang_data['cam' + concept_i + '_body'])) {
				concept_count++;
			}
		}		
		if (concept_count == 1) {
			var concept_i = 1;
			var table_concept_body_note_div = document.createElement('div');
			table_concept_body_note_div.classList.add('table_notes');
			table_concept_body_note_div.id = 'table_concept_' + concept_i + '_body';
			table_concept_body_note_div.innerHTML = table_data.lang_data['cam' + concept_i + '_body'];
			html_concepts_methods.appendChild(table_concept_body_note_div);			
			html_concepts_methods.style.display = null;
			html_concepts_methods_header.style.display = 'flex';				
		} else if (concept_count > 1) {
			for (var concept_i = 1; concept_i <= 20; concept_i++) {
				if ((table_data.lang_data['cam' + concept_i + '_title']) && (table_data.lang_data['cam' + concept_i + '_body'])) {					
					var concept_div = document.createElement('div');
					concept_div.classList.add('statistic_result_3');
					html_concepts_methods.appendChild(concept_div);					
					var subject_right_sub_title_div = document.createElement('div');
					subject_right_sub_title_div.classList.add('subject_right_sub_title');
					subject_right_sub_title_div.classList.add('margin_top_30');
					concept_div.appendChild(subject_right_sub_title_div);					
					var conceptsMethods_title_h = document.createElement('span');
					conceptsMethods_title_h.classList.add('h6');
					conceptsMethods_title_h.innerHTML = table_data.lang_data['cam' + concept_i + '_title'];
					var conceptsMethods_title_a = document.createElement('a');
					conceptsMethods_title_a.classList.add('expand_more_less');
					conceptsMethods_title_a.innerHTML = conceptsMethods_title_h.outerHTML + '<i class="material-icons" ><span class="dummy_collapse">Collapse</span></i>';
					conceptsMethods_title_a.href = "#conceptsMethods_" + concept_i;
					conceptsMethods_title_a.setAttribute("data-bs-toggle", "collapse");
					conceptsMethods_title_a.setAttribute("aria-expanded", "true");
					subject_right_sub_title_div.appendChild(conceptsMethods_title_a);					
					var conceptsMethods_div = document.createElement('div');
					conceptsMethods_div.classList.add('collapse');
					conceptsMethods_div.classList.add('show');
					conceptsMethods_div.id = 'conceptsMethods_' + concept_i;
					concept_div.appendChild(conceptsMethods_div);					
					var table_concept_body_div = document.createElement('div');
					table_concept_body_div.classList.add('table_concept_body');
					conceptsMethods_div.appendChild(table_concept_body_div);				
					var table_concept_body_note_div = document.createElement('div');
					table_concept_body_note_div.classList.add('table_notes');
					table_concept_body_note_div.id = 'table_concept_' + concept_i + '_body';
					table_concept_body_note_div.innerHTML = table_data.lang_data['cam' + concept_i + '_body'];
					table_concept_body_div.appendChild(table_concept_body_note_div);					
					html_concepts_methods.style.display = null;
					html_concepts_methods_header.style.display = 'flex';
				}
			}
		}
	}	
	var tb_subject_code_list = [];
	// breadcrumb
	if (table_data.lang_data.subject_list && table_data.lang_data.subject_list.length > 0) {
		var scode_string = 'scode';
		var old_url = document.referrer;
		var scode_position = old_url.indexOf(scode_string);
		var html_position = old_url.indexOf('.html');
		if (scode_position >= 0 && html_position >= 0) {
			if (html_position < scode_position) {
				subject_code = old_url.substring(scode_position + scode_string.length + 1);
				var and_position = subject_code.indexOf('&');
				if (and_position >= 0) {
					subject_code = subject_code.substring(0, and_position);
				}
			} else {
				subject_code = old_url.substring(scode_position + scode_string.length, html_position);
			}
		}
		tb_subject_code_list = getSubjectCodes(table_data);
		if (!window.isWebReport) {
			var exists = $.grep(tb_subject_code_list, function (f) { return f.subject === subject_code; })[0];
			if (!exists) {
				 exists = $.grep(tb_subject_code_list, function (f) { return f.primary; })[0];
			}
			subject_code = exists.subject;
			console.log("breadcrumb");
			showBreadcrumb("scode", subject_code);
		}
	}	
	// calculate the number of rows and columns header
	// permutate the cell data
	var column_data_list = [];
	permutateColumnRow(table_data, column_cell_list, column_data_list, 0, col_depth_obj, 0, 1);
	var column_header_count = column_data_list.length;
	var row_data_list = [];
	permutateColumnRow(table_data, row_cell_list, row_data_list, 0, row_depth_obj, 0, 1);
	var row_header_count = row_data_list.length;	
	// build HTML table header
	var header_row_1 = html_table.getElementsByTagName('thead')[0].insertRow(0);
	header_row_1.className = "hiddentrforExport";
	var header_cell_1 = header_row_1.insertCell(0);
	header_cell_1.id = table_id + TABLE_HEADER_CELL_ID_1;
	header_cell_1.className = "hiddentdforExport";
	header_cell_1.setAttribute("style", exportTableCellStyle);
	if (window.isWebReport) {
		header_cell_1.innerHTML = "<strong>" + $("#table_cap_" + table_data.table_id).html() + "</strong>";
	} else {
		if (table_data.table_title_string) {
			header_cell_1.innerHTML = "<strong>" + table_data.table_title_string + "</strong>";
		}	
	}
	var header_row_2 = html_table.getElementsByTagName('thead')[0].insertRow(1);
	header_row_2.className = "hiddentrforExport";
	var header_cell_2 = header_row_2.insertCell(0);
	header_cell_2.className = "hiddentdforExport";
	header_cell_2.setAttribute("style", exportTableCellStyle);
	header_cell_2.innerHTML = "&nbsp;";
	// build the HTML column header
	var sd_used_list = [];
	var row_counter = 0;
	var head_counter = 2;
	var isFirstCV = false;
	var last_column_cv_title = null;
	var last_column_cv_title_html = null;
	var tv_cnt = 0;
	for (var cv in table_data.ccyy_time_series_list) {
		if (table_data.lang_data.cv_list[cv].is_time_series === "1" && !indenpendent_tv_list.concat(no_ccyy_tv).includes(cv) && 
			table_data.ccyy_time_series_list[cv].filter(function (v) { return v.show; }).length > 0) {
			tv_cnt += 1;
		}
	}
	var first_tv = false;
	//$.each(column_data_list, function (column_index, column_row) {
	for (var column_index in column_data_list) {
		var column_row = column_data_list[column_index];		
		var last_element = false;
		if (column_index == column_data_list.length - 1) {
			last_element = true;
		}		
		var temp_column_header_span = 0;
		var first_record = null;
		for (var index in column_row){
			first_record = column_row[index];
			if (!first_record.is_dummy) {
				break;
			}
		}		
		if (first_record.is_sv) {
			var cell_counter = 0;
			var sv_row = html_table.getElementsByTagName('thead')[0].insertRow(head_counter);
			head_counter++;
			var sv_empty = sv_row.insertCell(cell_counter);
			cell_counter++;
			sv_empty.outerHTML = '<th class="titlesvcollf titlesvcol" rowspan="2" colspan="' + row_header_count + '">&nbsp;</th>';
			// group the sv
			var last_sv_cell = undefined;
			var last_sv_record = undefined;
			for (var sv_index in column_row) {
				var record = column_row[sv_index];				
				// check if all the items in the loopup path are show
				var show = record.sv_show && checkMdtLookupPathShow(table_data, record.mdt_lookup_path);
				if (show) {					
					// check if this sv is belong to different cc
					var same_sv = checkSameSvByLookupPath(last_sv_record, record);					
					// if same cc, then this sv may have several different sp, then merge this cell for sp
					if (last_sv_record && same_sv){
						last_sv_cell.colSpan = last_sv_cell.colSpan + record.span;
					} else {					
						var sv_cell = document.createElement("TH");
						setCellId(table_data, record, sv_cell);
						sv_row.appendChild(sv_cell);
						//sv_cell.setAttribute('data-t', 's');
						sv_cell.setAttribute('scope', 'col');
						cell_counter++;
						var sv_record = table_data.lang_data.sv_list[record.stat_var];
						sv_cell.innerHTML = createFootnote(sv_record, record.sv_text, footnote_used_list, table_data);
						setExportText(sv_cell, sv_cell.innerHTML);
						//sv_cell.setAttribute('data-v', sv_cell.innerHTML);
						sv_cell.className = 'titlesvcoltop titlesvcolrgtop titlesvcol';
						sv_cell.colSpan = record.span;						
						last_sv_cell = sv_cell;
						last_sv_record = record;
					}
					temp_column_header_span += record.span;				
					if (last_element || record.is_leaf) {
						column_mdt_lookup_path[cell_counter] = record.mdt_lookup_path;
					}
				}
			}			
		} else if (first_record.is_sp) {
			var cell_counter = 0;
			var sp_row = html_table.getElementsByTagName('thead')[0].insertRow(head_counter);
			head_counter++;
			for (var sp_index in column_row) {
				var record = column_row[sp_index];				
				// check if all the items in the loopup path are show
				var show = record.sp_show && checkMdtLookupPathShow(table_data, record.mdt_lookup_path);
				if (show) {
					var sp_cell = document.createElement("TH");
					setCellId(table_data, record, sp_cell);
					sp_row.appendChild(sp_cell);
					//sp_cell.setAttribute('data-t', 's');
					sp_cell.setAttribute('scope', 'col');
					cell_counter++;
					var sv_record = table_data.lang_data.sv_list[record.stat_var];
					var sp_record = sv_record.sp_list[record.stat_pres];
					sp_cell.innerHTML = createFootnote(sp_record, record.sp_text, footnote_used_list, table_data);
					setExportText(sp_cell, sp_cell.innerHTML);
					//sp_cell.setAttribute('data-v', sp_cell.innerHTML);
					sp_cell.className = 'titlesvcoldwn titlesvcolrgdwn titlesvcol';
					sp_cell.colSpan = record.span;
					temp_column_header_span += record.span;					
					if (last_element || record.is_leaf) {
						column_mdt_lookup_path[cell_counter] = record.mdt_lookup_path;
					}
				}				
			}			
		} else {
			// else cv			
			// get another first_record record if the class_var and class_code_group is null
			if (!first_record.class_var || !first_record.class_code_group) {
				for (var column_row_counter in column_row) {
					first_record = column_row[column_row_counter];
					if (first_record.class_var && first_record.class_code_group) {
						break;
					}
				}
			}			
			// if this column still only has null (dummy record), then increase last cell colspan
			if (!first_record.class_var) {
				if (last_column_cv_title) {
					last_column_cv_title.rowSpan++;
					html_table.getElementsByTagName('thead')[0].insertRow(head_counter);
					head_counter++;
				}
				continue;
			}
			var cell_counter = 0;
			var cv_row = html_table.getElementsByTagName('thead')[0].insertRow(head_counter);
			if (!isFirstCV) {
				isFirstCV = true;
				cv_row.classList.add("firstCVRow");
			}
			head_counter++;
			// get how mang ccg in this column_row list
			var cv_ccg_map = {};
			for (var cv_record_index in column_row) {
				var cv_record = column_row[cv_record_index];
				cv_ccg_map[cv_record.class_code_group] = true;
			}
			var cv_ccg_count = check_length(cv_ccg_map);
			// add cv / ccg description
			var cv_desc = table_data.lang_data.cv_list[first_record.class_var].def_class_desc;
			/*if (table_data.lang_data.cv_list[first_record.class_var].is_time_series === "1" && !first_tv && tv_cnt >= 1) {
				cv_desc = table_data.lang_data.cv_list[CCYY].def_class_desc;
				first_tv = true;
			}*/
			var cv_title_inner_html = '';
			var used_cv_desc = cv_desc;
			if (first_record.is_tv) {
				var result = getMultiTVDesc(column_row, table_data, footnote_used_list);
				cv_desc = result.cv_desc;
				used_cv_desc = result.used_cv_desc;
				cv_title_inner_html = result.cv_title_inner_html;
			} else {
				if (cv_ccg_count > 1) {
					// if there are more than 1 ccg for this data list, show the cv desc
					createFootnote(table_data.lang_data.cv_list[first_record.class_var], cv_desc, footnote_used_list, table_data);
					cv_title_inner_html = createFootnote(table_data.lang_data.cv_list[first_record.class_var], cv_desc, footnote_used_list, table_data);
				} else {
					var ccg_desc = table_data.lang_data.cv_list[first_record.class_var].ccg_list[first_record.class_code_group].ccg_desc;
					if (((typeof(idds) != 'undefined') && (idds)) || ((typeof(census21) != 'undefined') && (census21))) {
						// no need to use ccg description for 21C
						cv_title_inner_html = createFootnote(table_data.lang_data.cv_list[first_record.class_var], cv_desc, footnote_used_list, table_data);
					} else {
						if (ccg_desc != null) {
							cv_title_inner_html = ccg_desc;
							used_cv_desc = ccg_desc;
						} else {
							cv_title_inner_html = createFootnote(table_data.lang_data.cv_list[first_record.class_var], cv_desc, footnote_used_list, table_data);
						}
					}
				}
			}			
			var cv_title = null;
			if (last_column_cv_title && (last_column_cv_title_html == cv_title_inner_html)) {
				// merge the cv cell if text is the same
				last_column_cv_title.rowSpan++;
				last_column_cv_title.className = 'pac_titlecvcol';
				cv_title = last_column_cv_title;
			} else {
				var cv_title = document.createElement("TH");
				setCellId(table_data, used_cv_desc, cv_title);
				cv_row.appendChild(cv_title);
				cv_title.setAttribute('scope', 'row');
				cv_title.setAttribute('data-t', 's');
				cell_counter++;
				cv_title.innerHTML = cv_title_inner_html;
				if ((typeof(idds) != 'undefined') && (idds) && (typeof(IDDS_CV_POPUP_CODE) != 'undefined')) {
					cv_title.setAttribute('data-text_only', cv_title.innerHTML);
					cv_title.innerHTML = cv_title.innerHTML + IDDS_CV_POPUP_CODE;
				}
				setExportText(cv_title, cv_title_inner_html);
				cv_title.setAttribute('data-class_var', first_record.class_var);
				cv_title.className = 'titlecvcol';
				if (row_header_count > 0) {
					cv_title.colSpan = row_header_count;
				}
				cv_title.no_ccyy_tv_added = false;
			}
			column_mdt_lookup_path = [];		
			column_row_loop:
			for (var cc_index in column_row) {
				var record = column_row[cc_index];				
				// check if all the items in the loopup path are show
				var parent_show = checkMdtLookupPathShow(table_data, record.mdt_lookup_path, record);
				var show = record.show && parent_show;				
				// special handling for No CCYY TV show
				if (no_ccyy_tv.includes(record.class_var)) {
					// get the CCYY
					if (record.mdt_lookup_path.length > 0) {
						for (var looup_record_index in record.mdt_lookup_path) {
							var looup_record = record.mdt_lookup_path[looup_record_index];
							if ((!looup_record.is_sv) && (looup_record.class_var == CCYY)) {								
								if ((table_data.ccyy_time_series_map[record.class_var][looup_record.class_code]) && (table_data.ccyy_time_series_map[record.class_var][looup_record.class_code][record.class_code])){
									var ccyy_time_series_record = table_data.ccyy_time_series_map[record.class_var][looup_record.class_code][record.class_code];
									// skip this No CCYY TV if not selected to show
									if (!ccyy_time_series_record.show) {
										continue column_row_loop;
									}
								}
							}
						}
					}
				}			
				if (record.is_dummy) {					
				} else if (show) {
					var cc_cell = document.createElement("TH");
					setCellId(table_data, record, cc_cell);
					cc_cell.setAttribute("scope", "col");
					cv_row.appendChild(cc_cell);
					cell_counter++;
					var record_text = record.text;					
					// special handling for No CCYY TV text
					if (no_ccyy_tv.includes(record.class_var)) {
						cc_cell.setAttribute('data-' + record.class_var, 'row');			
						// get the CCYY
						if (record.mdt_lookup_path.length > 0) {
							for (var looup_record_index in record.mdt_lookup_path) {
								var looup_record = record.mdt_lookup_path[looup_record_index];
								if ((!looup_record.is_sv) && (looup_record.class_var == CCYY)) {
									record_text = getMMYearString(looup_record.class_code, record_text);
								}
							}
						}						
					}
					// special handling for QoQ text
					if (record.class_var == QoQ) {
						cc_cell.setAttribute('data-QoQ', 'row');
						// get the CCYY
						if (record.mdt_lookup_path.length > 0) {
							for (var looup_record_index in record.mdt_lookup_path) {
								var looup_record = record.mdt_lookup_path[looup_record_index];
								if ((!looup_record.is_sv) && (looup_record.class_var == CCYY)) {
									record_text = getQQYearString(looup_record.class_code, record_text);
								}
							}
						}						
					}
					if (record.class_var == CCYY) {
						cc_cell.setAttribute('data-CCYY', true);
					}					
					var cc_record = getCC(table_data, record.class_var, record.class_code);
					record_text = createFootnote(cc_record, record_text, footnote_used_list, table_data);
					if (record.sd_values) {
						record_text = setCvSdValue(table_data, record, record.sd_value_array, record_text, sd_used_list);
					}
					if (record.ccyy_sd_values) {
						record_text = setCvSdValue(table_data, record, record.ccyy_sd_value_array, record_text, sd_used_list);
					}					
					cc_cell.innerHTML = record_text;
					cc_cell.setAttribute('data-t', 's');
					if (record.class_code == '') {
						cc_cell.className = 'titletotalcol';
					} else {
						cc_cell.className = 'titlecol';
					}
					cc_cell.colSpan = record.span;
					setExportText(cc_cell, record_text);
					temp_column_header_span += record.span;				
					if (record.other_span) {
						cc_cell.rowSpan = record.other_span;						
						if (column_index == column_data_list.length - record.other_span) {
							last_element = true;
						}
					}
				}
				if ((last_element || record.is_leaf) && parent_show && (record.is_dummy || show)) {
					column_mdt_lookup_path[cc_index] = record.mdt_lookup_path;
				}
			}
			last_column_cv_title = cv_title;
			last_column_cv_title_html = cv_title_inner_html;			
		}
	};
	
	column_mdt_lookup_path = [];
	var total_columns = 0; //column_data_list[column_data_list.length - 1].length;
	if (column_data_list && column_data_list.length > 0) {
		column_data_list[0].forEach(function (v) {
			if (v.show || v.sv_show || v.sp_show) {
				if (v.span) {
					total_columns += v.span;
				} else {
					total_columns += 1;
				}
			}
		});
	}
	var rowHeader_colspan = total_columns + row_header_count;
	header_cell_1.colSpan = rowHeader_colspan;
	header_cell_2.colSpan = rowHeader_colspan;
	var column_is_total = [];
	column_data_list.forEach(function (p) {
		var idx = -1;
		p.forEach(function (v) {
			var ori_idx = idx;
			idx += (v.span ? v.span : 1);
			if (v.show || v.sv_show || v.sp_show) {
				for (var i = ori_idx + 1; i <= idx; i++) {
					if (!column_is_total[i]) {
						column_is_total[i] = v.is_total ? true : false;
					}
				}
			}
			if (v.is_leaf && (v.show || v.sv_show || v.sp_show)) {
				if (!column_mdt_lookup_path[idx]) {
					column_mdt_lookup_path[idx] = v.mdt_lookup_path;
				} else {
					errorLog("Table column index [" + idx + "]", "duplicated");
					errorLog("The original look up path is", "", column_mdt_lookup_path[idx]);
					errorLog("The current node is", "", v);
				}
			}
		});
	});
	// build the HTML row header (CV title)
	//var row_header = html_table.getElementsByTagName('tbody')[0].insertRow(row_counter);
	//row_counter++;
	if (!no_data) {
		var row_header = html_table.getElementsByTagName('thead')[0].insertRow(head_counter);
		head_counter++;
		var row_header_cell_counter = 0;	
		var last_row_index = null;
		var last_cv_title = null;
		for (var row_index in row_data_list) {
			var row_column = row_data_list[row_index];		
			var first_record = row_column[0];
			if (first_record.is_sv) {		
				var sv_empty = row_header.insertCell(row_header_cell_counter);
				row_header_cell_counter++;
				sv_empty.outerHTML = "<th scope='row' class='titlesvrow' colspan='2'></th>";
			} else if (first_record.is_sp) {
				// sv colSpan already include this SP
			} else {	//cv, get another first_record record if the class_var and class_code_group is null
				if (!first_record.class_var || !first_record.class_code_group) {
					for (var row_column_counter in row_column) {
						first_record = row_column[row_column_counter];
						if (first_record.class_var && first_record.class_code_group) {
							break;
						}
					}
				}			
				// if this column still only has null (dummy record), then increase last cell colspan
				if (!first_record.class_var) {
					if (last_cv_title) {
						last_cv_title.colSpan++;
					}
					continue;
				}			
				// get how mang ccg in this row_column list
				var cv_ccg_map = {};
				for (var cv_record_index in row_column) {
					var cv_record = row_column[cv_record_index];
					cv_ccg_map[cv_record.class_code_group] = true;
				}
				var cv_ccg_count = check_length(cv_ccg_map);			
				// add cv / ccg description
				var cv_desc = table_data.lang_data.cv_list[first_record.class_var].def_class_desc;
				var used_cv_desc = cv_desc;
				var cv_title_inner_html = '';
				if (first_record.is_tv) {
					var result = getMultiTVDesc(row_column, table_data, footnote_used_list);
					cv_desc = result.cv_desc;
					used_cv_desc = result.used_cv_desc;
					cv_title_inner_html = result.cv_title_inner_html;
				} else {	
					if (cv_ccg_count > 1) {
						// if there are more than 1 ccg for this data list, show the cv desc
						cv_title_inner_html = createFootnote(table_data.lang_data.cv_list[first_record.class_var], cv_desc, footnote_used_list, table_data);
					} else {
						var ccg_desc = table_data.lang_data.cv_list[first_record.class_var].ccg_list[first_record.class_code_group].ccg_desc;
						if (((typeof(idds) != 'undefined') && (idds)) || ((typeof(census21) != 'undefined') && (census21))) {
							// no need to use ccg description for 21C
							cv_title_inner_html = createFootnote(table_data.lang_data.cv_list[first_record.class_var], cv_desc, footnote_used_list, table_data);
						} else {
							if (ccg_desc != null) {
								cv_title_inner_html = ccg_desc;
								used_cv_desc = ccg_desc;
							} else {
								cv_title_inner_html = createFootnote(table_data.lang_data.cv_list[first_record.class_var], cv_desc, footnote_used_list, table_data);
							}
						}
					}
				}			
				var cv_title = null;
				if (last_cv_title && ($(last_cv_title).html() === $("<span>" + cv_title_inner_html + "</span>").html())) {	//& sign and other special char may cause difference
					cv_title = last_cv_title;
					//var span = row_column.sort(function (a, b) { if (a.other_span > b.other_span) { return 1; } else { return -1; } })[0].other_span;
					//last_cv_title.colSpan += (span ? span : 1);
					last_cv_title.colSpan ++;
					last_cv_title.className += ' pac_titlecvrow';
				} else {
					var cv_title = document.createElement("TD");
					setCellId(table_data, used_cv_desc, cv_title);
					row_header.appendChild(cv_title);
					cv_title.setAttribute('scope', 'row');
					cv_title.setAttribute('data-t', 's');
					cv_title.setAttribute('data-class_var', first_record.class_var);
					row_header_cell_counter++;
					cv_title.innerHTML = cv_title_inner_html;
					if ((typeof(idds) != 'undefined') && (idds) && (typeof(IDDS_CV_POPUP_CODE) != 'undefined')) {
						cv_title.setAttribute('data-text_only', cv_title.innerHTML);
						cv_title.innerHTML = cv_title.innerHTML + IDDS_CV_POPUP_CODE;
					}
					cv_title.className = 'titlecvrow pseudoth';
					if (first_record.is_sv) {
						cv_title.setAttribute("data-cell_type", "sv");
					} else if (first_record.is_tv) {
						cv_title.setAttribute("data-cell_type", "tv");
					} else {
						cv_title.setAttribute("data-cell_type", first_record.class_var);
					}				
					setExportText(cv_title, cv_title.innerHTML);					
					// check if there is a skip in row_index
					/*if (last_cv_title && last_row_index && (row_index - last_row_index > 1)) {
						// then last title's column span is equal to the skipped col
						console.log("*** colspan changed");
						//last_cv_title.colSpan = row_index - last_row_index;
					}*/				
				}
				last_cv_title = cv_title;
			}		
			last_row_index = row_index;
		}
		// fill in the grey cell for the rest of the row
		var blank_title = row_header.insertCell(row_header_cell_counter);
		blank_title.innerHTML = "";
		blank_title.className = 'titleblank';
		blank_title.colSpan = total_columns;
	}
	var space = "&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; ";
	for (var i = 1; i < 10; i++) {
		space += space;
	}
	//$(blank_title).html("<div class='scrollbar' onscroll='scrollbardivScrolling(this);' style='display: none;'><div>" + space + "</div></div>");
	// build the HTML row header (SV / SP and CC)
	var row_data_header = html_table.getElementsByTagName('tbody')[0].insertRow(row_counter);
	row_counter++;
	var row_cell_counter = 0;
	var data_list = row_data_list[0];	
	var buildRowHeaderPromises = function () {
		var promises_res = [];
		row_counter = buildRowHeaderHtml(html_table, row_data_header, row_counter, row_cell_counter, data_list, column_mdt_lookup_path, table_data, row_header_count, sd_used_list, row_data_list, footnote_used_list, promises_res, column_is_total, false);
		return Promise.all(promises_res);
	}	
	buildRowHeaderPromises().then(function (results) {
		addPseudoCellsforPAC(html_table);
		addCVTitleID(html_table);
		table_data.sd_used_list = sd_used_list;
		table_data.footnote_used_list = footnote_used_list;
		generateNotes(table_data, keep_note);
		addHiddenNotes(table_data, rowHeader_colspan, html_table);
		if (!window.isWebReport) {
			if (!table_data.dict_generated) {	//data dictionary re-generated without glossary after submit button clicked
				generateDataDictionary(table_data);
				table_data.dict_generated = true;
				loadGlossaryInMap(table_data);
			} else {
				applyKeyword("#table_notes");	//table notes and sources are rebuilt
				applyKeyword("#table_source");
			}			
		}
		table_data_list[table_id].lang_data = table_data.lang_data;
		table_data_list[table_id].component_data = table_data.component_data;
		table_data_list[table_id].notes_data = table_data.notes_data;
		table_data_list[table_id].sd_used_list = table_data.sd_used_list;
		table_data_list[table_id].source_data = table_data.source_data;	
		calculateTableRowHeaderWidth(html_table.id);
		if (tb_subject_code_list.length > 0) {
			// resolve the promise with our result			
			if (table_resolve[table_id]) {
				table_resolve[table_id]({
					subject_code_list: tb_subject_code_list,
					table_data: table_data
				});
				//console.warn(table_id);
			}
		} else {
			if (table_resolve[table_id]) {
				table_resolve[table_id]({
					subject_code_list: [],
					table_data: table_data
				});
			}
			//buildTableCharts(table_data);
		}
		table_data.time.build_table_time = new Date(); 
		table_data.time.build_table_cost = table_data.time.build_table_time - table_data.time.remove_empty_cell_time;
		//console.log(table_data.time);
		if (!window.isWebReport) {
			if (api_popup) {
				showApiPopup();
			}		
			if (option_popup) {
				option_popup = false;
				openCust();
			}
			if (download_sdmx) {
				loadSdmx(table_data).then(function (v) {
					if (v && v.length > 0) {
						generateSdmx();
					} else {
						errorLog("SDMX", "No SDMX can be downloaded");
					}
				});
			}
			if (download_excel) {
				generateDefault('Excel', false);
			}
			if (download_excel_excl) {
				generateDefault('Excel', true);
			}
			if (download_csv) {
				generateDefault('csv', false);
			}
			if (download_csv_excl) {
				generateDefault('csv', true);
			}
			if (download_csv_tabular) {
				generateDefault('csv_tabular', false);
			}
			if (download_xml) {
				//generateXml();
				generateDefault('xml', false);
			}
		}
	});
}

function addPseudoCellsforPAC(tbl) {	//table contains cells with colspan / rowspan like 1 2, 2 1 in different rows with out any 1 1 1 cell cannot show correctly
	var firstTr = $(tbl).find("tbody").find("tr")[0];
	var totalCols = 0;
	var pseudoTd = "<td class='pseudotd' style='min-width: 0px !important; display: contents'>&nbsp</td>";
	var pseudoTd2 = "<td class='pseudotd' style=''></td>";
	var pseudoTd3 = $(pseudoTd).html("")[0].outerHTML;
	if (firstTr) {		
		$(firstTr).children().toArray().forEach(function (v) {
			var colspan = $(v).attr("colspan");
			if (colspan) {
				totalCols += parseInt(colspan);
			} else {
				totalCols += 1;
			}
		});
		var html = ""
		for (var i = 0; i < totalCols; i++) {
			html += pseudoTd2;
		}
		if (html) {
			html = "<tr class='pseudotr'>" + html + "</tr>";
		}
		$(tbl).find("tbody").append(html);
		$(tbl).find("tr").toArray().forEach(function (v) {
			if (!v.classList || !v.classList.contains("pseudotr")) {
				$(v).append(pseudoTd);
			} else {
				$(v).append(pseudoTd3);
			}
		});
	}
	
}

function getMultiTVDesc(src, table_data, footnote_used_list) {
	var tvs = [];				
	var cv_desc = "";
	var used_cv_desc = "";
	var cv_title_inner_html = "";
	groupBy(src, function (v) { return v.class_var; }).forEach(function (v, k) { 
		if (v[0].class_var) {
			tvs.push(v[0]);
			var desc = table_data.lang_data.cv_list[v[0].class_var].def_class_desc;
			cv_desc += desc + " / ";
			if (((typeof(idds) != 'undefined') && (idds)) || ((typeof(census21) != 'undefined') && (census21))) {
				cv_title_inner_html += createFootnote(table_data.lang_data.cv_list[v[0].class_var], desc, footnote_used_list, table_data) + " / ";
			} else {
				var ccg_desc = table_data.lang_data.cv_list[v[0].class_var].ccg_list[v[0].class_code_group].ccg_desc;
				if (ccg_desc != null) {
					cv_title_inner_html += ccg_desc + " / ";
					used_cv_desc += ccg_desc + " / ";
				} else {
					cv_title_inner_html += createFootnote(table_data.lang_data.cv_list[v[0].class_var], desc, footnote_used_list, table_data) + " / ";
				}
			}
		}
	});
	if (cv_desc) {
		cv_desc = cv_desc.substring(0, cv_desc.length - 3);
	}
	if (used_cv_desc) {
		used_cv_desc = used_cv_desc.substring(0, used_cv_desc.length - 3);
	}
	used_cv_desc = cv_desc + " " + used_cv_desc;
	if (cv_title_inner_html) {
		cv_title_inner_html = cv_title_inner_html.substring(0, cv_title_inner_html.length - 3);
	}
	return {
		cv_desc: cv_desc,
		used_cv_desc: used_cv_desc,
		cv_title_inner_html: cv_title_inner_html
	}
}

function addCVTitleID(html_table) {
	if (html_table) {
		/*var ids = "";
		var blank = $(html_table).find(".titleblank")[0];
		if (blank) {
			var ths = $(blank).parent().children("th").toArray().reverse();
			ths.forEach(function (v) {
				ids += v.id + " ";
			});
			ids = ids.trim();
		}
		if (ids) {
			$(html_table).find("td").toArray().forEach(function (v) {
				var headers = $(v).attr("headers");
				if (headers) {
					var i = 0;
					var hdrs = headers.split(" ");
					ids.split(" ").forEach(function (id) {
						if (!hdrs.includes(id)) {
							hdrs.splice(hdrs.length - 1 - i, 0, id);
						}
						i += 2;
					});
					$(v).attr("headers", hdrs.join(" "));
				}
			});
		}*/
		//$(html_table).find("th").removeAttr("headers");
		//$(html_table).find("td").removeAttr("headers");	//too many td will cause maximum call stack error
		var th = $(html_table).children("thead")[0];
		var tb = $(html_table).children("tbody")[0];
		if (th) {
			var thr = $(th).children("tr");
			if (thr && thr.length > 0) {
				$(thr).children("th").removeAttr("headers");
				$(thr).children("td").removeAttr("headers");
			}
		}
		if (tb) {
			var tbr = $(tb).children("tb");
			if (tbr && tbr.length > 0) {
				$(tbr).children("th").removeAttr("headers");
				$(tbr).children("td").removeAttr("headers");
			}
		}
	}
}

// check if all the items in the loopup path are show
function checkMdtLookupPathShow(table_data, mdt_lookup_path, record) {	
	for (var path_index in mdt_lookup_path) {	
		var mdt_lookup_path_record = mdt_lookup_path[path_index];	
		if (mdt_lookup_path_record == undefined) {	
			// skip this, maybe col or row span > 1, so no record for this path	
			continue;	
		}	
		if (mdt_lookup_path_record.is_sv) {	
			var temp_sv_record = table_data.lang_data.sv_list[mdt_lookup_path_record.stat_var];	
			if (!temp_sv_record.show ||
				!temp_sv_record.sp_list[mdt_lookup_path_record.stat_pres].show) {
				return false;	
			}				
		} else {				
			mdt_lookup_path_record.class_code	
			var temp_cv_record = table_data.lang_data.cv_list[mdt_lookup_path_record.class_var];	
			for (var temp_ccg_index in temp_cv_record.ccg_list) {	
				var temp_ccg_record = temp_cv_record.ccg_list[temp_ccg_index];	
				if (temp_ccg_record.cc_list[mdt_lookup_path_record.class_code] && 
					temp_ccg_record.cc_list[mdt_lookup_path_record.class_code].cc_index && 
					!temp_ccg_record.cc_list[mdt_lookup_path_record.class_code].show) {
					/*if (mdt_lookup_path_record.class_var === CCYY && record.children) {
						if (checkCCYYChildrenShow(table_data, record)) {
							return true;
						}
					}*/
					return false;	
				}	
			}	
		}	
	}	
	return true;	
}

// check if this sv is belong to different cc
function checkSameSvByLookupPath(last_sv_record, record) {	
	if (last_sv_record) {	
		if (last_sv_record.mdt_lookup_path.length != record.mdt_lookup_path.length) {	
			return false;	
		} else {	
			for (var m_index = 0;  m_index < record.mdt_lookup_path.length; m_index++) {	
				var mdt_lookup_path_record_1 = record.mdt_lookup_path[m_index];	
				var mdt_lookup_path_record_2 = last_sv_record.mdt_lookup_path[m_index];					
				if (!mdt_lookup_path_record_1 || !mdt_lookup_path_record_2) {	
					// skip this, maybe col or row span > 1, so no record for this path	
					return false;	
				}	
				if (mdt_lookup_path_record_1.is_sv != mdt_lookup_path_record_2.is_sv) {	
					return false;	
				}	
				if (mdt_lookup_path_record_1.is_sv && mdt_lookup_path_record_1.stat_var != mdt_lookup_path_record_2.stat_var) {
					return false;	
				}					
				if (!mdt_lookup_path_record_1.is_sv
					&& ((mdt_lookup_path_record_1.class_var != mdt_lookup_path_record_2.class_var)	
					|| (mdt_lookup_path_record_1.class_code != mdt_lookup_path_record_2.class_code))) {	
					return false;	
				}	
			}	
		}	
	}	
	return true;	
}

function buildRowHeaderHtml(html_table, row_data_header, row_counter, row_cell_counter, data_list, column_mdt_lookup_path, table_data, row_header_count, sd_used_list, row_data_list, footnote_used_list, promises_res, column_total_array, row_is_total) {
	var current_row_data_header = row_data_header;
	var current_row_cell_counter = row_cell_counter;
	var first_record = first(data_list);
	var first_data = true;
	if (first_record && first_record.is_sv) {
		// group the sv
		var last_sv_cell = undefined;
		var last_sv_record = undefined;		
		for (var sv_index in data_list) {			
			var record = data_list[sv_index];
			if (!record.sv_show) {
				continue;
			}			
			if (first_data) {
				first_data = false;
			} else {
				current_row_data_header = html_table.getElementsByTagName('tbody')[0].insertRow(row_counter);
				row_counter++;
				current_row_cell_counter = 0;
			}			
			// check if this sv is belong to different cc
			var same_sv = checkSameSvByLookupPath(last_sv_record, record);			
			// if same cc, then this sv may have several different sp, then merge this cell for sp
			if ((last_sv_record != undefined) && same_sv){
				last_sv_cell.rowSpan = last_sv_cell.rowSpan + record.span;
			} else {
				var sv_cell = document.createElement("TH");
				setCellId(table_data, record, sv_cell);
				current_row_data_header.appendChild(sv_cell);
				sv_cell.setAttribute('scope', 'row');
				//sv_cell.setAttribute('data-t', 's');
				current_row_cell_counter++;
				var sv_record = table_data.lang_data.sv_list[record.stat_var];
				sv_cell.innerHTML = createFootnote(sv_record, record.sv_text, footnote_used_list, table_data);
				setExportText(sv_cell, sv_cell.innerHTML);
				//sv_cell.setAttribute('data-v', sv_cell.innerHTML);
				sv_cell.className = 'titlesvrow';
				sv_cell.setAttribute("data-cell_type", "sv");
				sv_cell.rowSpan = record.span;				
				last_sv_cell = sv_cell;
				last_sv_record = record;
			}			
			if (check_length(record.children) > 0) {
				row_counter = buildRowHeaderHtml(html_table, current_row_data_header, row_counter, current_row_cell_counter, record.children, column_mdt_lookup_path, table_data, row_header_count, sd_used_list, row_data_list, footnote_used_list, promises_res, column_total_array, row_is_total || record.is_total);
			}
		}		
	} else if (first_record && first_record.is_sp) {
		for (var sp_index in data_list) {			
			var record = data_list[sp_index];
			if (!record.sp_show) {
				continue;
			}			
			if (first_data) {
				first_data = false;
			} else {
				current_row_data_header = html_table.getElementsByTagName('tbody')[0].insertRow(row_counter);
				row_counter++;
				current_row_cell_counter = 0;
			}			
			var sp_cell = document.createElement("TH");
			setCellId(table_data, record, sp_cell);
			current_row_data_header.appendChild(sp_cell);
			//sp_cell.setAttribute('data-t', 's');
			sp_cell.setAttribute('scope', 'row');
			current_row_cell_counter++;
			var sv_record = table_data.lang_data.sv_list[record.stat_var];
			var sp_record = sv_record.sp_list[record.stat_pres];
			sp_cell.innerHTML = createFootnote(sp_record, record.sp_text, footnote_used_list, table_data);
			setExportText(sp_cell, sp_cell.innerHTML);
			//sp_cell.setAttribute('data-v', sp_cell.innerHTML);
			sp_cell.className = 'titlesvrow';
			sp_cell.setAttribute("data-cell_type", "sv");
			sp_cell.rowSpan = record.span;
			if (check_length(record.children) > 0) {
				row_counter = buildRowHeaderHtml(html_table, current_row_data_header, row_counter, current_row_cell_counter, record.children, column_mdt_lookup_path, table_data, row_header_count, sd_used_list, row_data_list, footnote_used_list, promises_res, column_total_array, row_is_total || record.is_total);
			} else {	// reach end, build the mdt
				buildMdtHtml(table_data, column_mdt_lookup_path, current_row_data_header, current_row_cell_counter, sd_used_list, record, column_total_array, row_is_total || record.is_total);
			}
		}		
	} else {	// add cv / ccg description
		data_list_loop:
		for (var cc_index in data_list) {			
			var record = data_list[cc_index];			
			if (!record || !record.show) {
				continue;
			}
			// for No CCYY TV
			if (no_ccyy_tv.includes(record.class_var)) {
				if (record.mdt_lookup_path.length > 0) {
					for (var looup_record_index in record.mdt_lookup_path) {
						var looup_record = record.mdt_lookup_path[looup_record_index];
						if ((!looup_record.is_sv) && (looup_record.class_var == CCYY)) {							
							if ((table_data.ccyy_time_series_map[record.class_var][looup_record.class_code]) && (table_data.ccyy_time_series_map[record.class_var][looup_record.class_code][record.class_code])){
								var ccyy_time_series_record = table_data.ccyy_time_series_map[record.class_var][looup_record.class_code][record.class_code];
								// skip this No CCYY TV if not selected to show
								if (!ccyy_time_series_record.show) {
									continue data_list_loop;
								}
							} else {	// skip this No CCYY TV if it does not exist
								continue data_list_loop;
							}
						}
					}
				}
			}
			if (first_data) {
				first_data = false;
			} else {
				current_row_data_header = html_table.getElementsByTagName('tbody')[0].insertRow(row_counter);
				row_counter++;
				current_row_cell_counter = 0;
			}			
			var cc_cell = document.createElement("TH");
			setCellId(table_data, record, cc_cell);
			current_row_data_header.appendChild(cc_cell);
			cc_cell.setAttribute("scope", "row");
			current_row_cell_counter++;			
			var p = new Promise(function (resolve, reject) {
				var indent_string = '';
				// for parent and child
				for (var i = 0; i < record.indent; i++) {
					indent_string = indent_string + '&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;';
				}				
				var record_text = record.text;
				if (no_ccyy_tv.includes(record.class_var)) {	// for No CCYY TV
					cc_cell.setAttribute('data-' + record.class_var, 'column');
					if (record.mdt_lookup_path.length > 0) {	// get the CCYY
						for (var looup_record_index in record.mdt_lookup_path) {
							var looup_record = record.mdt_lookup_path[looup_record_index];
							if ((!looup_record.is_sv) && (looup_record.class_var == CCYY)) {
								record_text = getMMYearString(looup_record.class_code, record_text);
							}
						}
					}
				}
				if (record.class_var == QoQ) {	// for QoQ
					cc_cell.setAttribute('data-QoQ', 'column');
					// get the CCYY
					if (record.mdt_lookup_path.length > 0) {
						for (var looup_record_index in record.mdt_lookup_path) {
							var looup_record = record.mdt_lookup_path[looup_record_index];
							if ((!looup_record.is_sv) && (looup_record.class_var == CCYY)) {
								record_text = getQQYearString(looup_record.class_code, record_text);
							}
						}
					}
				}
				var original_record_text = record_text;				
				var cc_record = null;
				if (!record.is_dummy) {
					cc_record = getCC(table_data, record.class_var, record.class_code);
				}
				record_text = createFootnote(cc_record, record_text, footnote_used_list, table_data);
				if (record.sd_values) {
					record_text = setCvSdValue(table_data, record, record.sd_value_array, record_text, sd_used_list);					
				}
				if (record.ccyy_sd_values) {
					record_text = setCvSdValue(table_data, record, record.ccyy_sd_value_array, record_text, sd_used_list);
				}
				var cell_indent = 20 * record.indent;
				cc_cell.setAttribute('data-t', 's');
				if (cell_indent != 0) {
					cc_cell.innerHTML = '<div style="margin-left: ' + cell_indent + 'px;">' + record_text + '</div>';
				} else {
					cc_cell.innerHTML = record_text;
				}
				setExportText(cc_cell, record_text, indent_string);
				cc_counter[table_data.table_id]++;
				cc_cell_id_map['cc_id_' + table_data.table_id + '_' + cc_counter[table_data.table_id]] = cc_cell.id;
				cc_counter_map[table_data.table_id][cc_counter[table_data.table_id]] = null;
				if (!record.is_sv && record.class_var == CCYY) {
					cc_cell.setAttribute('data-CCYY', true);
				}
				if (record.class_code == '') {
					cc_cell.className = 'titletotalrow';
				} else {
					if ((record.pac) && (record.pac.length > 0)) {
						cc_cell.className = 'pac_titlerow';
					} else {
						cc_cell.className = 'titlerow';
					}
				}
				if (record.is_sv) {
					cc_cell.setAttribute("data-cell_type", "sv");
				} else if (record.is_tv) {
					cc_cell.setAttribute("data-cell_type", "tv");
				} else {
					cc_cell.setAttribute("data-cell_type", record.class_var);
				}
				cc_cell.rowSpan = record.span;				
				if (record.other_span) {
					cc_cell.colSpan = record.other_span;
				}
				resolve();
			});
			promises_res.push(p);			
			if (check_length(record.children) > 0) {
				row_counter = buildRowHeaderHtml(html_table, current_row_data_header, row_counter, current_row_cell_counter, record.children, column_mdt_lookup_path, table_data, row_header_count, sd_used_list, row_data_list, footnote_used_list, promises_res, column_total_array, row_is_total || record.is_total);
			} else {
				// reach end, build the mdt
				buildMdtHtml(table_data, column_mdt_lookup_path, current_row_data_header, current_row_cell_counter, sd_used_list, record, column_total_array, row_is_total || record.is_total);
			}
		}
	}	
	return row_counter;
}

function setExportText(cell, record_text, indent_string) {
	cell.setAttribute('data-html_text', cell.innerHTML);	
	var excel_text = (indent_string ? indent_string : "") + record_text;
	["super", "sub"].forEach(function (t) {
		var tag = t.substring(0, 3);
		excel_text = excel_text.replaceAll("<" + tag, "<span style='vertical-align: " + t + "'").replaceAll("</" + tag + ">", "</span>");
	});
	cell.setAttribute('data-excel_text', excel_text);
}

function setCvSdValue(table_data, record, sd_value_array, record_text, sd_used_list) {
	var new_sd_value_array = [];	
	// no need to show sd value if the children show the same sd value
	for (var sd_index in sd_value_array) {
		var record_sd_value = sd_value_array[sd_index];
		var record_sd_value_exist = false;
		for (var child_index in record.children) {
			var child_record = record.children[child_index];
			if (child_record.sd_value_array && child_record.sd_value_array.indexOf(record_sd_value) >= 0) {
				record_sd_value_exist = true;
				break;
			}
		}
		if (!record_sd_value_exist) {
			new_sd_value_array.push(record_sd_value);
		}
	}
	var new_sd_values = new_sd_value_array.join()
	var sd_result = createSdText(table_data, new_sd_values, record_text + ' ', sd_used_list);
	record_text = sd_result.sd_text;
	return record_text;
}

function getLookupPathCvUsed(cv_used, mdt_lookup_path) {
	for (var temp_path_index in mdt_lookup_path) {
		var temp_path_record = mdt_lookup_path[temp_path_index];
		if (!temp_path_record) {
			continue;	// skip this, maybe col or row span > 1, so no record for this path
		}
		if (!temp_path_record.is_sv) {
			cv_used.push(temp_path_record.class_var);
		}
	}
}

function buildMdtHtml(table_data, column_mdt_lookup_path, current_row_data_header, current_row_cell_counter, sd_used_list, record, column_total_array, row_is_total) {
	var p = new Promise(function (resolve, reject) {
		buildMdtHtmlInner(table_data, column_mdt_lookup_path, current_row_data_header, current_row_cell_counter, sd_used_list, record, column_total_array, row_is_total);
		resolve();
	});
}	

function buildMdtHtmlInner(table_data, column_mdt_lookup_path, current_row_data_header, current_row_cell_counter, sd_used_list, record, column_total_array, row_is_total) {
	var row_temp_mdt_data = [];
	for (var temp_stat_var in table_data.mdt_data) {
		row_temp_mdt_data[temp_stat_var] = [];
		for (var temp_stat_pres in table_data.mdt_data[temp_stat_var]) {
			row_temp_mdt_data[temp_stat_var][temp_stat_pres] = table_data.mdt_data[temp_stat_var][temp_stat_pres].slice(0);
		}
	}
	//var has_total = filterMdt(row_temp_mdt_data, record.mdt_lookup_path, true);
	filterMdt(row_temp_mdt_data, record.mdt_lookup_path, true);
	// filter the mdt for this row
	// build a list of CV used in this row
	var row_cv_used = [];
	getLookupPathCvUsed(row_cv_used, record.mdt_lookup_path);	
	// filter the mdt by the criteria apply to this table
	if (table_data.lookup_path) {
		filterMdt(row_temp_mdt_data, table_data.lookup_path, false);
		getLookupPathCvUsed(row_cv_used, table_data.lookup_path);
	}
	var table_notes_element = document.getElementById(table_data.table_id + '_' + table_notes);
	var add_table_id_to_sd_symbol = false;
	if (table_notes_element) {
		add_table_id_to_sd_symbol = true;
	}	
	for (var column_index in column_mdt_lookup_path) {		
		//var column_has_total = has_total;
		var temp_mdt_data = [];
		for (var temp_stat_var in row_temp_mdt_data) {
			temp_mdt_data[temp_stat_var] = [];
			for (var temp_stat_pres in row_temp_mdt_data[temp_stat_var]) {
				temp_mdt_data[temp_stat_var][temp_stat_pres] = row_temp_mdt_data[temp_stat_var][temp_stat_pres].slice(0);
			}
		}		
		var mdt_lookup_path = column_mdt_lookup_path[column_index];
		//column_has_total = filterMdt(temp_mdt_data, mdt_lookup_path, false) || column_has_total;
		filterMdt(temp_mdt_data, mdt_lookup_path, false);
		var cv_used = row_cv_used.slice(0);
		getLookupPathCvUsed(cv_used, mdt_lookup_path);	
		// filter the mdt with extra condition
		var actual_mdt = [];
		var mdt_cell = current_row_data_header.insertCell(current_row_cell_counter);
		current_row_cell_counter++;		
		mdt_counter[table_data.table_id]++;
		mdt_cell.id = 'mdt_id_' + table_data.table_id + '_' + mdt_counter[table_data.table_id];
		mdt_counter_map[table_data.table_id][mdt_counter[table_data.table_id]] = null;
		setMdtCellHeaders(table_data, record, mdt_lookup_path, mdt_cell);
		mdt_cell.setAttribute('data-t', 'n');		
		for (var mdt_sv_index in temp_mdt_data) {
			var mdt_sv = temp_mdt_data[mdt_sv_index];
			for (var mdt_sp_index in mdt_sv) {
				var mdt_sp = mdt_sv[mdt_sp_index];				
				var current_sp = table_data.lang_data.sv_list[mdt_sv_index].sp_list[mdt_sp_index];				
				// remove mdt with extra conditions
				var mdt_record = getMdtRecordWithoutExtraCondition(mdt_sp, cv_used, table_data);
				if (mdt_record) {
					// fill in special display
					var sd_text = '';
					var sd_values = mdt_record['sd_value'];
					var sd_result = createSdText(table_data, sd_values, sd_text, sd_used_list, mdt_record.ignore_sd_values);
					sd_text = sd_result.sd_text;
					var suppressed = sd_result.suppressed;
					if (suppressed) {
						mdt_cell.innerHTML = sd_text;
						mdt_cell.setAttribute('data-no_sd', '');
						mdt_cell.setAttribute('data-mdt_obs_value_no_sd_text', '');
						mdt_cell.setAttribute('data-obs_value_numeric_sd', sd_result.sd_symbol);
						mdt_cell.setAttribute('data-mdt_obs_value_sd_text', sd_result.sd_symbol);
						mdt_record.mdt_obs_value_text = '';
						mdt_record.mdt_obs_value_no_sd_text = '';
						mdt_cell.setAttribute('data-t', 's');
						mdt_cell.setAttribute('data-has_sd_text', true);
					} else {
						var current_obs_value = createObsValueText(mdt_record, current_sp, true);						
						var obs_value_numeric = current_obs_value.replace(/ /g, '');
						obs_value_numeric = obs_value_numeric.replace(/,/g, '');
						obs_value_numeric = obs_value_numeric.replace('+', '');
						mdt_record.mdt_obs_value_no_sd_text = obs_value_numeric;						
						obs_value_numeric = Number(obs_value_numeric);
						mdt_cell.setAttribute('data-no_sd', obs_value_numeric);
						mdt_cell.setAttribute('data-mdt_obs_value_no_sd_text', mdt_record.mdt_obs_value_no_sd_text);
						mdt_cell.setAttribute('data-obs_value_numeric_sd', (current_obs_value + ' ' + sd_result.sd_symbol).trim());
						mdt_cell.setAttribute('data-mdt_obs_value_sd_text', (mdt_record.mdt_obs_value_no_sd_text + ' ' + sd_result.sd_symbol).trim());
						if (sd_result.sd_symbol) {
							mdt_cell.setAttribute('data-has_sd_text', true);
						} else {
							mdt_cell.setAttribute('data-has_sd_text', false);
						}
						if (sd_text) {
							mdt_cell.innerHTML = (current_obs_value + ' ' + sd_text).trim();
						} else {
							mdt_cell.textContent = current_obs_value;
						}
						mdt_record.mdt_obs_value_text = current_obs_value;
					}					
					mdt_record.mdt_sv_index = mdt_sv_index;
					mdt_record.mdt_sp_index = mdt_sp_index;
					mdt_counter_map[table_data.table_id][mdt_counter[table_data.table_id]] = mdt_record;
				} else {	// NA
					var sd_record = table_data.sd_list[na_sd_value];
					if (sd_used_list.indexOf(na_sd_value) < 0) {
						sd_used_list.push(na_sd_value);
					}
					if (window.isWebReport) {
						if (add_table_id_to_sd_symbol) {
							sd_text = '<a href="#' + (table_data ? table_data.table_id + "_" : "") + sd_record.sd_symbol + '" class="cdm_footnote">' + sd_record.sd_symbol + '</a>';
						} else {
							sd_text = '<a href="#' + (table_data ? table_data.table_id + "_" : "") + sd_record.sd_symbol + '" class="cdm_footnote">' + sd_record.sd_symbol + '</a>';
						}
					} else {
						if (typeof default_demographics_lookup_path !== 'undefined') {
							sd_text = '<a href="#' + sd_record.sd_symbol + '" class="cdm_footnote" style="text-decoration: underline;">' + sd_record.sd_symbol + '</a>';
						} else {
							if (add_table_id_to_sd_symbol) {
								sd_text = '<a href="#' + (table_data ? table_data.table_id + "_" : "") + sd_record.sd_symbol + '" class="cdm_footnote" style="text-decoration: underline;">' + sd_record.sd_symbol + '</a>';
							} else {
								sd_text = '<a href="#' + (table_data ? table_data.table_id + "_" : "") + sd_record.sd_symbol + '" class="cdm_footnote" style="text-decoration: underline;">' + sd_record.sd_symbol + '</a>';
							}
						}
					}
					mdt_cell.innerHTML = sd_text;
					mdt_cell.setAttribute('data-no_sd', '');
					mdt_cell.setAttribute('data-mdt_obs_value_no_sd_text', '');
					mdt_cell.setAttribute('data-obs_value_numeric_sd', sd_record.sd_symbol);
					mdt_cell.setAttribute('data-mdt_obs_value_sd_text', sd_record.sd_symbol);
					mdt_cell.setAttribute('data-has_sd_text', true);
					mdt_cell.setAttribute('data-t', 's');
				}				
				if (mdt_record) {
					var zValue = processExcelFormat(parseFloat(mdt_record.obs_value), current_sp.excel_separator_format, current_sp.def_decimals, removeHtmlCode(mdt_cell.innerHTML));
					if (zValue) {
						mdt_cell.setAttribute('data-z', zValue);
					}
				} else {
					if (current_sp.excel_separator_format) {
						mdt_cell.setAttribute('data-z', current_sp.excel_separator_format);
					}
				}
			}
		}
		mdt_cell.setAttribute('data-original_value',  mdt_cell.innerHTML);
		if (row_is_total || record.is_total || column_total_array[column_index]) {
			mdt_cell.className = 'datatotal';
		} else {
			mdt_cell.className = 'data';
		}
	}
}

function processExcelFormat(val, fmt, dp_setting, default_fmt) {
	var result = fmt;
	if (val) {
		var dp = ""
		if (fmt && fmt.includes("# #")) {
			result = result.trim();
			var tmp = "";
			var idx1 = fmt.indexOf(".");
			/*if (idx1 === -1) {
				idx1 = fmt.indexOf("_");
			}*/
			var idx2 = -1;
			if (idx1 >= 0) {
				idx2 = fmt.indexOf(";", idx1);
				if (idx2 >= 0) {
					dp = fmt.substring(idx1, idx2);
				} else {
					dp = fmt.substring(idx1);
				}
			} else if (dp_setting > 0) {
				for (var i = 0; i < parseInt(dp_setting); i++) {
					dp += "0";
				}
				dp = "." + dp;
			}
			var cnt = 0;
			val = Math.abs(val);
			while (val >= 1) {
				val = val / 10;
				tmp = "#" + (cnt % 3 === 0 && cnt > 0 ? " " : "") + tmp;
				cnt += 1;
			}
			if (tmp) {
				tmp = tmp.substring(0, tmp.length - 1) + "0" + dp;
			} else {
				tmp += "0" + dp;
			}
			result = tmp;
			if (fmt.indexOf("+") >= 0) {
				result = "+" + result;
				if (fmt.indexOf("_") >= 0) {
					result += "_ ";
				}
			}
			if (fmt.indexOf("-") >= 0) {
				result += ";-" + tmp;
			} else if (fmt.indexOf("(") >= 0) {
				result += ";(" + tmp + ")";
			}
			if (fmt.split(";").length === 3) {
				result += ";0" + dp;
			}		
		}
		if (!result) {
			result = "";
			var pointFound = false;
			for (var i = 0; i < default_fmt.length; i++) {
				var ch = default_fmt.substring(i, i + 1);
				if (ch === ".") {
					pointFound = true;
					result = result.substring(0, result.length - 1) + "0" + ch;
				} else {
					if (pointFound) {
						result += "0";
					} else {
						if (is_Numeric(ch)) {
							result += "#";
						} else {
							if (ch !== "-") {
								result += ch;
							}
						}
					}
				}
			}
			if (!pointFound) {
				result = result.substring(0, result.length - 1) + "0" + (val > 0 ? "_" : "");
			}
			result += " ";
		}
	}
	return result;
}

function createSdText(table_data, sd_values, sd_text, sd_used_list, ignore_sd_values) {
	return createSdFromListText(table_data.sd_list, sd_values, sd_text, sd_used_list, ignore_sd_values, table_data);
}

function createSdFromListText(sd_list, sd_values, sd_text, sd_used_list, ignore_sd_values, table_data) {
	var add_table_id_to_sd_symbol = false;
	if (table_data) {
		var table_notes_element = document.getElementById(table_data.table_id + '_' + table_notes);
		if (table_notes_element) {
			add_table_id_to_sd_symbol = true;
		}
	}
	var suppressed = false;
	var sd_symbol = '';
	if (sd_values) {
		var sd_value_array = sd_values.split(',');
		for (var sd_value_index in sd_value_array) {
			var sd_value = sd_value_array[sd_value_index];
			if (ignore_sd_values && ignore_sd_values.indexOf(sd_value) >= 0) {
				continue;
			}				
			var sd_record = sd_list[sd_value];
			if (sd_record) {
				if (sd_record.obs_value_suppressed == '1') {
					suppressed = true;
				}
				if (sd_record.sd_symbol) {
					if (window.isWebReport) {
						if (add_table_id_to_sd_symbol) {
							sd_text = sd_text + '<a href="#' +(table_data ? table_data.table_id + "_" : "") + sd_record.sd_symbol + '" class="cdm_footnote">' + sd_record.sd_symbol + '</a>';
						} else {
							sd_text = sd_text + '<a href="#' + (table_data ? table_data.table_id + "_" : "") + sd_record.sd_symbol + '" class="cdm_footnote">' + sd_record.sd_symbol + '</a>';
						}
					} else {
						if (typeof default_demographics_lookup_path !== 'undefined') {
							sd_text = sd_text + '<a href="#' + sd_record.sd_symbol + '" class="cdm_footnote" style="text-decoration: underline;">' + sd_record.sd_symbol + '</a>';
						} else {
							if (add_table_id_to_sd_symbol) {
								sd_text = sd_text + '<a href="#' + (table_data ? table_data.table_id + "_" : "") + sd_record.sd_symbol + '" class="cdm_footnote" style="text-decoration: underline;">' + sd_record.sd_symbol + '</a>';
							} else {
								sd_text = sd_text + '<a href="#' + (table_data ? table_data.table_id + "_" : "") + sd_record.sd_symbol + '" class="cdm_footnote" style="text-decoration: underline;">' + sd_record.sd_symbol + '</a>';
							}
						}
					}
					if (sd_symbol) {
						sd_symbol = sd_symbol + ',';
					}
					sd_symbol = sd_symbol + sd_record.sd_symbol;
					if (sd_used_list.indexOf(sd_value) < 0) {
						sd_used_list.push(sd_value);
					}
				}
			}
		}
	}
	var result = {
		sd_text : sd_text,
		suppressed : suppressed,
		sd_symbol : sd_symbol
	};
	return result;
}

function createObsValueText(mdt_record, sp_record, need_thousand_separator, for_chart) {
	(1.005).toFixed(2) == "1.01" || (function (prototype) {
		var toFixed = prototype.toFixed;
		prototype.toFixed = function (fractionDigits) {
			var split = this.toString().split('.');
			if ((split.length > 1) && (split[1].length > fractionDigits)) {
				var number = +(!split[1] ? split[0] : split.join('.') + '1')
			} else if (split.length > 1) {
				var zero = '';
				for (var f = split[1].length; f < fractionDigits; f++) {
					zero = zero + '0';
				}
				return split.join('.') + zero;
			} else {
				if (fractionDigits > 0) {
					var zero = '';
					for (var f = 0; f < fractionDigits; f++) {
						zero = zero + '0';
					}
					return split[0] + '.' + zero;
				} else {
					return split[0];
				}
			}
			return toFixed.call(number, fractionDigits)
	  }
	}(Number.prototype));
	var v = Number(mdt_record['obs_value']);
	var sp_v = v;
	if (sp_record) {
		if (sp_record.def_decimals > 0) {
			sp_v = v.toFixed(sp_record.def_decimals);
		} else if (sp_record.def_decimals < 0) {
			var pow = Math.pow(10, -sp_record.def_decimals);
			v = Math.round(v / pow) * pow;
			sp_v = v;
		} else if (sp_record.def_decimals == 0) {
			sp_v = Math.round(v);
		}		
		if (need_thousand_separator) {
			sp_v = setThousandSeparator(sp_v, sp_record, for_chart);
		}
	}
	return sp_v;
}

function filterMdtObject(obj, mdt_lookup_path) {
	for (var l_index in mdt_lookup_path) {
		var mdt_lookup = mdt_lookup_path[l_index];
		var temp_cv = mdt_lookup.class_var;
		var temp_cc = mdt_lookup.class_code;
		if (!mdt_lookup.ignore_mdt_grep) {
			if (temp_cc) {
				if (obj[temp_cv] != temp_cc) {
					return false;
				}
			} else {	// for total, may not have mdt attribute
				if (!(obj[temp_cv] == '' || !obj[temp_cv])) {
					return false;
				}
			}
		}
	}
	return true;
}

function filterMdt(temp_mdt_data, mdt_lookup_path, is_row) {
	var has_total = false;
	var temp_mdt_lookup_path = [];
	$.grep(mdt_lookup_path, function (v) { return v; }).forEach(function (mdt_lookup) {
		temp_mdt_lookup_path.push(mdt_lookup);
		if (mdt_lookup.is_sv) {
			var temp_sv = mdt_lookup.stat_var;
			var temp_sp = mdt_lookup.stat_pres;	
			for (var mdt_sv_index in temp_mdt_data) {
				var mdt_sv = temp_mdt_data[mdt_sv_index];
				if (mdt_sv_index == temp_sv) {
					for (var mdt_sp_index in mdt_sv) {
						if (mdt_sp_index !== temp_sp) {
							delete mdt_sv[mdt_sp_index];	// remove sp
						}
					}
				} else {
					delete temp_mdt_data[mdt_sv_index];	// remove sv
				}
			}
		} else {
			var temp_cv = mdt_lookup.class_var;
			var temp_cc = mdt_lookup.class_code;			
			if (temp_cc == '') {
				has_total = true;
			}			
			for (var mdt_sv_index in temp_mdt_data) {
				if (!cacheMdtData[mdt_sv_index]) {
					cacheMdtData[mdt_sv_index] = [];
				}				
				var mdt_sv = temp_mdt_data[mdt_sv_index];
				for (var mdt_sp_index in mdt_sv) {
					if (!cacheMdtData[mdt_sv_index][mdt_sp_index]) {
						cacheMdtData[mdt_sv_index][mdt_sp_index] = [];
					}
					var mdt_sp = mdt_sv[mdt_sp_index];
					if (!mdt_lookup.ignore_mdt_grep) {						
						var temp_mdt_lookup_path_string = '';
						if (is_row) {
							temp_mdt_lookup_path_string = arrayToString(temp_mdt_lookup_path);
						}
						if (is_row && cacheMdtData[mdt_sv_index][mdt_sp_index][temp_mdt_lookup_path_string]) {
							mdt_sp = cacheMdtData[mdt_sv_index][mdt_sp_index][temp_mdt_lookup_path_string];
						} else {
							if (temp_cc) {
								mdt_sp = $.grep(mdt_sp, function (obj) { return (obj[temp_cv] == temp_cc); });
							} else {
								// for total, may not have mdt attribute
								mdt_sp = $.grep(mdt_sp, function (obj) { return (obj[temp_cv] == '') || (!obj[temp_cv]); });
							}
							if (is_row) {
								cacheMdtData[mdt_sv_index][mdt_sp_index][temp_mdt_lookup_path_string] = mdt_sp;
							}
						}
					}
					mdt_sv[mdt_sp_index] = mdt_sp;
				}
			}
		}
	});
	return has_total;
}

function permutateColumnRow(table_data, column_row_cell_list, column_row_data_list, level, depth_obj, column_row_depth, previous_depth) {
	for (var cell_index in column_row_cell_list) {
		var cell_record = column_row_cell_list[cell_index];
		if (cell_record == null) {
			continue;
		}		
		if (cell_record.is_sv) {
			if (column_row_data_list[level] == undefined) {
				column_row_data_list[level] = [];
			}
			if (column_row_data_list[level + 1] == undefined) {
				column_row_data_list[level + 1] = [];
			}			
			column_row_data_list[level].push(cell_record);
			var cell_record_sp = JSON.parse(JSON.stringify(cell_record));
			cell_record.children = [cell_record_sp];
			cell_record.is_leaf = false;	//sv and sp are the same cell when build header objects, but they are separated when building table headers
			cell_record_sp.is_sv = false;
			cell_record_sp.is_sp = true;
			column_row_data_list[level + 1].push(cell_record_sp);
			permutateColumnRow(table_data, cell_record_sp.children, column_row_data_list, level + 2, depth_obj, column_row_depth + 1, 1);
		} else {
			if (column_row_data_list[level] == undefined) {
				column_row_data_list[level] = [];
			}
			column_row_data_list[level].push(cell_record);
			var insert_dummy_record = false;
			if (check_length(cell_record.children) > 0) {
				var next_depth = 1;
				if (cell_record.other_span > 1) {
					next_depth = cell_record.other_span;
				}
				permutateColumnRow(table_data, cell_record.children, column_row_data_list, level + next_depth, depth_obj, column_row_depth + next_depth, next_depth);				
				if (cell_record.other_span > 1) {
					insert_dummy_record = true;
				}
			} else if (depth_obj.depth > level){
				insert_dummy_record = true;
			}		
			if (insert_dummy_record) {
				var dummy_depth = cell_record.other_span - 1;
				var dummy_record = {
					class_var: null,
					class_code_group: null,
					mdt_lookup_path: cell_record.mdt_lookup_path,
					show: true,
					span: cell_record.span,
					is_dummy: true
				};				
				for (var d = 1; d <= dummy_depth; d++) {
					if (column_row_data_list[level + d] == undefined) {
						column_row_data_list[level + d] = [];
					}
					column_row_data_list[level + d].push(dummy_record);
				}
			}
		}
	}	
}

function buildColumnRowTree(table_data, column_row_array, column_row_index, cell_record_structure, depth_obj, original_mdt_filtered_sv_sp_list) {
	var result = [];
	if (column_row_index > depth_obj.depth) {
		depth_obj.depth = column_row_index;
	}	
	var reverse_cell_list = column_row_array[column_row_index].cell_list.slice();	//reverse the list for easy parent and child checking
	if (!column_row_array[column_row_index].is_tv || !table_data.component_data.rev_chrono) {
		reverse_cell_list.reverse();
	}
	var last_loop_cell_record = null;
	var no_match_count = 0;
	for (var cell_index in reverse_cell_list) {
		var temp_cell_record = reverse_cell_list[cell_index];
		// remove the child cell if it is the same cc with parent and child, but different indent 
		//then update the indent
		if (last_loop_cell_record && !last_loop_cell_record.is_sv && 
			last_loop_cell_record.class_var == temp_cell_record.class_var && 
			last_loop_cell_record.class_code == temp_cell_record.class_code) {			
			last_loop_cell_record.indent = temp_cell_record.indent;
			continue;
		}
		var cell_record = clone(temp_cell_record);
		var temp_cell_record_structure = cell_record_structure.slice();			
		if (cell_record.class_code == '') {	
		// no need to check if class_code is total
			if (cell_record_structure.length > 0) {
				var last_cell_record = cell_record_structure[cell_record_structure.length - 1];
				// same class_var as last level, and this record is total.  
				//Which mean this is pac show total at bottom.  No need to check mdt lookup for this total
				if ((last_cell_record.class_var !== undefined) && (last_cell_record.class_var == cell_record.class_var)) {
					cell_record.ignore_mdt_grep = true;					
					if (last_cell_record.class_code == cell_record.class_code) {	
						// then just merge these 2 cell
						if (last_cell_record.other_span) {
							last_cell_record.other_span++;
						} else {
							last_cell_record.other_span = 2;
						}
					}
				}
			}
			temp_cell_record_structure.push(cell_record);
		} else if (cell_record.is_sv || cell_record.class_code != '') {
			var replace_record_path = false;
			if (cell_record_structure.length > 0) {
				var last_cell_record = cell_record_structure[cell_record_structure.length - 1];
				if ((last_cell_record.class_var !== undefined) && (last_cell_record.class_var == cell_record.class_var)) {					
					if (last_cell_record.pac && last_cell_record.class_code) {	
						// if same class_var, but not parent child relation, skip this record
						var parent_matched = false;
						for (var pac_index in last_cell_record.pac) {
							var child_record = last_cell_record.pac[pac_index];
							if (child_record.class_code == cell_record.class_code) {
								//if (!child_record.duplicated) {
									parent_matched = true;
									break;
								/*}*/
							}
						}						
						if (!parent_matched) {
							no_match_count += 1;
							continue;
						}
					}				
					// if same class_var, but last_cell_record is total, then skip this record if this record is not total
					if (!last_cell_record.class_code && cell_record.class_code) {
						no_match_count += 1;
						continue;
					}
					// if same class_var, but last_cell_record is not total, then skip this record if this record is total
					if (last_cell_record.class_code && !cell_record.class_code) {
						no_match_count += 1;
						continue;
					}
					// if this record is exactly the same as last_cell_record, then just merge these 2 cell
					if (last_cell_record.class_code == cell_record.class_code) {
						if (last_cell_record.other_span) {
							last_cell_record.other_span++;
						} else {
							last_cell_record.other_span = 2;
						}							
						if (column_row_array.length <= column_row_index + 1) {
							return [];
						} else {
							result = [];
						}
					}
					// only add to the list if it is the child
					replace_record_path = true;
				}
			}			
			if (replace_record_path) {
				// replace the last record
				temp_cell_record_structure[temp_cell_record_structure.length - 1] = cell_record;				
				// the original_mdt_filtered_sv_sp_list also need to recalculate
				original_mdt_filtered_sv_sp_list = table_data.mdt_data;
			} else {
				// check if it needs to handle parent and child relationship for searching criteria
				temp_cell_record_structure.push(cell_record);
			}
		}
		var temp_mdt_filtered_sv_sp_list = original_mdt_filtered_sv_sp_list;
		if (table_data.lookup_path) {
			temp_mdt_filtered_sv_sp_list = [];
			for (var k in original_mdt_filtered_sv_sp_list) {
				temp_mdt_filtered_sv_sp_list[k] = [];
				for (var l in original_mdt_filtered_sv_sp_list[k]) {
					temp_mdt_filtered_sv_sp_list[k][l] = original_mdt_filtered_sv_sp_list[k][l].slice(0);
				}
			}
			filterMdt(temp_mdt_filtered_sv_sp_list, table_data.lookup_path, false);
		}
		// check mdt exist
		var mdt_data_exist = false;
		var mdt_lookup_path = [];
		var mdt_filtered_list = [];
		var mdt_filtered_sv_sp_list = [];		
		var mdt_record_list = [];		
		for (var mdt_sv_index in temp_mdt_filtered_sv_sp_list) {
			var mdt_sv = temp_mdt_filtered_sv_sp_list[mdt_sv_index];
			mdt_filtered_sv_sp_list[mdt_sv_index] = [];
			for (var mdt_sp_index in mdt_sv) {
				var mdt_sp = mdt_sv[mdt_sp_index];
				var temp_mdt_lookup_path = [];				
				// create the searching criteria by the list of sv / sp / cv and cc
				for (var cell_index in temp_cell_record_structure) {
					var test_cell_record = temp_cell_record_structure[cell_index];
					if (test_cell_record.is_sv) {
						depth_obj.has_sv = true;
						var temp_sv = test_cell_record.stat_var;
						var temp_sp = test_cell_record.stat_pres;
						if (mdt_sv_index == temp_sv && mdt_sp_index == temp_sp) {	// correct mdt
							temp_mdt_lookup_path.push({
								is_sv: true,
								stat_var: temp_sv,
								stat_pres: temp_sp,
								ignore_mdt_grep: false
							});
						} else {	// other mdt
							mdt_sp = [];
						}
					} else {
						var temp_cv = test_cell_record.class_var;
						var temp_cc = test_cell_record.class_code;
						if (!test_cell_record.ignore_mdt_grep) {
							if (temp_cc) {
								mdt_sp = $.grep(mdt_sp, function (obj) { return (obj[temp_cv] == temp_cc); });
							} else {	// for total, may not have mdt attribute
								mdt_sp = $.grep(mdt_sp, function (obj) { return (obj[temp_cv] == '') || (!obj[temp_cv]); });
							}
						}
						temp_mdt_lookup_path.push({
							is_sv: false,
							class_var: temp_cv,
							class_code: temp_cc,
							def_class_code_desc: test_cell_record.text,
							class_code_group: test_cell_record.class_code_group,
							ignore_mdt_grep: test_cell_record.ignore_mdt_grep,
							is_tv: test_cell_record.is_tv
						});
					}
				}				
				if (mdt_sp.length > 0) {					
					// check if the mdt has any unused CV
					var table_cv_list = [];
					for (var cv_value in table_data.cv_index_map) {
						table_cv_list.push(cv_value);
					}					
					mdt_record_list = mdt_record_list.concat(mdt_sp);
				}
				mdt_filtered_sv_sp_list[mdt_sv_index][mdt_sp_index] = mdt_sp;				
				if (temp_cell_record_structure.length == temp_mdt_lookup_path.length) {
					mdt_lookup_path = temp_mdt_lookup_path;
				}
			}
		}	// end temp_mdt_filtered_sv_sp_list loop		
		if (mdt_record_list.length > 0) {
			mdt_data_exist = true;
			mdt_filtered_list.push(mdt_record_list);		
			// special handling for non CCYY time series
			/*if ((!cell_record.is_sv) &&
				(table_data.lang_data.cv_list[cell_record.class_var].group_sd_value == '1')) {
				// check mdt_sp's sd value
				var new_sd_value_array = [];					
				if (mdt_record_list[0].sd_value) {
					var sd_value_array = mdt_record_list[0].sd_value.split(',');
					sd_value_array = sd_value_array.filter(Boolean);
					if (sd_value_array.length > 0) {						
						// ignore suppressed sd value
						for (var sd_value_index in sd_value_array) {
							var sd_value = sd_value_array[sd_value_index];
								
							var sd_record = table_data.sd_list[sd_value];
							if (sd_record) {
								if (sd_record.obs_value_suppressed == '1') {
									suppressed = true;
								} else {
									// check if the sd exist in last level
									var sd_value_exist = false;
									for (var cell_record_i in cell_record_structure) {
										var old_cell_record = cell_record_structure[cell_record_i];
										if ((old_cell_record.sd_value_array) && (old_cell_record.sd_value_array.indexOf(sd_value) >= 0)){
											sd_value_exist = true;
											// remove parent sd value
											const remove_index = old_cell_record.sd_value_array.indexOf(sd_value);
											if (remove_index > -1) {
												if (old_cell_record.can_remove_sd_value_array == undefined) {
													old_cell_record.can_remove_sd_value_array = [];
												}
												old_cell_record.can_remove_sd_value_array.push(sd_value);
											}
										}
									}
									new_sd_value_array.push(sd_value);
								}
							}
						}
						new_sd_value_array.sort();
						var new_ccyy_sd_value_array = new_sd_value_array.slice();						
						new_sd_value_array = checkMdtSdValueList(mdt_record_list, new_sd_value_array);
						if (new_sd_value_array.length > 0) {
							cell_record.sd_values = new_sd_value_array.join()
							cell_record.sd_value_array = new_sd_value_array;							
							for (var temp_mdt_index in mdt_record_list) {
								var temp_mdt = mdt_record_list[temp_mdt_index];
								if (temp_mdt.ignore_sd_values == undefined) {
									temp_mdt.ignore_sd_values = [];
								}								
								for (var sd_i in new_sd_value_array) {
									var temp_sd_value = new_sd_value_array[sd_i];
									if (temp_mdt.ignore_sd_values.indexOf(temp_sd_value) < 0) {
										temp_mdt.ignore_sd_values.push(temp_sd_value);
									}
								}
							}
						} 
					}
				}	
				if (new_sd_value_array.length == 0) {							
					// special handling for CCYY
					if (cell_record.class_var == CCYY) {
						var time_series_mdt_record_list = mdt_record_list.slice();
						for (var check_time_series_cv in table_data.lang_data.cv_list) {
							if (check_time_series_cv == CCYY) {
								continue;
							}
							var check_time_series_cv_record = table_data.lang_data.cv_list[check_time_series_cv];
							if (check_time_series_cv_record.is_time_series == '1') {
								time_series_mdt_record_list = $.grep(time_series_mdt_record_list, function (obj) { return (obj[check_time_series_cv] == '') || (!obj[check_time_series_cv]); });
							}
						}						
						if (time_series_mdt_record_list.length > 0) {
							var sd_value_array = time_series_mdt_record_list[0].sd_value.split(',');
							sd_value_array = sd_value_array.filter(Boolean);
							if (sd_value_array.length > 0) {								
								// ignore suppressed sd value
								new_sd_value_array = [];
								for (var sd_value_index in sd_value_array) {
									var sd_value = sd_value_array[sd_value_index];
										
									var sd_record = table_data.sd_list[sd_value];
									if (sd_record) {
										if (sd_record.obs_value_suppressed == '1') {
											suppressed = true;
										} else {
											new_sd_value_array.push(sd_value);
										}
									}
								}
								new_sd_value_array.sort();
								var new_ccyy_sd_value_array = new_sd_value_array.slice();
								new_ccyy_sd_value_array = checkMdtSdValueList(time_series_mdt_record_list, new_ccyy_sd_value_array);								
								if (new_ccyy_sd_value_array.length > 0) {
									cell_record.ccyy_sd_values = new_ccyy_sd_value_array.join();
									cell_record.ccyy_sd_value_array = new_ccyy_sd_value_array;									
									for (var temp_mdt_index in time_series_mdt_record_list) {
										var temp_mdt = time_series_mdt_record_list[temp_mdt_index];
										if (temp_mdt.ignore_sd_values == undefined) {
											temp_mdt.ignore_sd_values = [];
										}										
										for (var sd_i in new_ccyy_sd_value_array) {
											var temp_sd_value = new_ccyy_sd_value_array[sd_i];
											if (temp_mdt.ignore_sd_values.indexOf(temp_sd_value) < 0) {
												temp_mdt.ignore_sd_values.push(temp_sd_value);
											}
										}
									}
								}
							}
						}
					}
				}
			}*/
		}		
		// check sd value uses in all column / row
		if ((!cell_record.is_sv)) {
			var is_first_record = true;
			var sd_value_array = [];
			for (var mdt_sv_index in mdt_filtered_sv_sp_list) {
				var mdt_sv = mdt_filtered_sv_sp_list[mdt_sv_index];
				for (var mdt_sp_index in mdt_sv) {
					var mdt_sp = mdt_sv[mdt_sp_index];					
					for (var temp_mdt_sp_index in mdt_sp) {
						var temp_mdt = mdt_sp[temp_mdt_sp_index];						
						if (is_first_record) {
							is_first_record = false;
							if (temp_mdt.sd_value) {
								sd_value_array = temp_mdt.sd_value.split(',');
								sd_value_array = sd_value_array.filter(Boolean)
								if (sd_value_array.length > 0) {
									sd_value_array.sort();
								} else {
									break;
								}
							}
						} else {
							if (temp_mdt.sd_value) {
								var temp_mdt_sd_array = temp_mdt.sd_value.split(',');
								temp_mdt_sd_array.sort();
								sd_value_array = intersect_safe(sd_value_array, temp_mdt_sd_array);
								if (sd_value_array.length == 0) {
									break;
								}
							}
						}
					}
				}			
			}			
			// set sd value for this cv
			if (false && sd_value_array.length > 0) {	// TODO
				cell_record.sd_values = sd_value_array.join()				
				// set ignore sd value for the selected mdt
				for (var mdt_sv_index in mdt_filtered_sv_sp_list) {
					var mdt_sv = mdt_filtered_sv_sp_list[mdt_sv_index];
					for (var mdt_sp_index in mdt_sv) {
						var mdt_sp = mdt_sv[mdt_sp_index];
						for (var temp_mdt_index in mdt_sp) {
							var temp_mdt = mdt_sp[temp_mdt_index];
							if (temp_mdt.ignore_sd_values == undefined) {
								temp_mdt.ignore_sd_values = [];
							}							
							for (var sd_i in sd_value_array) {
								var temp_sd_value = sd_value_array[sd_i];
								if (!temp_mdt.ignore_sd_values.includes(temp_sd_value)) {
									temp_mdt.ignore_sd_values.push(temp_sd_value);
								}
							}
						}
					}
				}
			}
		}		
		cell_record.mdt_lookup_path = mdt_lookup_path;
		/*for (var pac_index in cell_record.pac) {
			var pac_record = cell_record.pac[pac_index];
			if (pac_record.mdt_data_exist) {
				mdt_data_exist = true;
				break;
			}
		}*/
		var nexts = getNextNodeIdx(cell_record, column_row_array, column_row_index);
		nexts.forEach(function (idx) {
			var newNode = clone(cell_record);
			if (idx === -999 || idx === -9999) {	//leaf node
				mdt_data_exist = checkMdtExists(table_data, newNode, column_row_array, mdt_filtered_sv_sp_list, mdt_data_exist, false);
				newNode.mdt_data_exist = mdt_data_exist;
				if (cell_record.is_tv && cell_record.tv_display_seq <= 0) {
					newNode.show = false;
				}
				if (mdt_data_exist) {
					newNode.span = 1;
					if ((last_cell_record) && (last_cell_record.class_var !== undefined) && (last_cell_record.class_var == newNode.class_var) && (last_cell_record.class_code == cell_record.class_code)) {
						if (last_cell_record.class_code) {
							if (last_cell_record.other_span) {
								last_cell_record.other_span++;
							} else {
								last_cell_record.other_span = 2;
							}
						}
					} else if (newNode.show === undefined || newNode.show) {
						if (idx === -9999) {
							if (newNode.other_span) {
								newNode.other_span++;
							} else {
								newNode.other_span = 2;
							}
						}						
						result.push(newNode);
						last_loop_cell_record = newNode;
					}
				}
				// also update the original object
				temp_cell_record.mdt_data_exist = mdt_data_exist;
			} else {
				if (idx < - 1000) {
					if (newNode.other_span) {
						newNode.other_span++;
					} else {
						newNode.other_span = 2;
					}
				}
				if (idx < 0) {
					idx *= -1;
					idx = idx % 100;
				}
				if (newNode.is_tv) {
					newNode.children = buildColumnRowTree(table_data, column_row_array, idx, temp_cell_record_structure, depth_obj, mdt_filtered_sv_sp_list);
				} else {
					do {
						newNode.children = buildColumnRowTree(table_data, column_row_array, idx, temp_cell_record_structure, depth_obj, mdt_filtered_sv_sp_list);
						if (newNode.children.all_no_match) {
							idx += 1;
							if (newNode.other_span) {
								newNode.other_span += 1;
							} else {
								newNode.other_span = 2;
							}
						}
						if (idx === column_row_array.length) {
							newNode.children = [];
							break;
						}
					} while (newNode.children.all_no_match);
				}
				var pac_mdt_data_exist = checkMdtExists(table_data, newNode, column_row_array, mdt_filtered_sv_sp_list, pac_mdt_data_exist, true);
				if (newNode.children && newNode.children.length > 0 && newNode.children[0].escape_level && newNode.children[0].escape_level > 0) {
					var spans = newNode.children[0].escape_level;
					if (newNode.other_span) {
						newNode.other_span += spans;
					} else {
						newNode.other_span = 1 + spans;
					}
				} else if (newNode.children && newNode.children.length === 1 && newNode.children[0].is_total && ((!newNode.is_sv && newNode.class_var === newNode.children[0].class_var) || (newNode.is_sv && newNode.stat_var === newNode.children[0].stat_var))) {
					var temp_span = newNode.children[0].other_span;
					if (!temp_span) {
						temp_span = 1;
					}
					if (newNode.other_span) {
						newNode.other_span += temp_span;
					} else {
						newNode.other_span = 1 + temp_span;
					}
					var remove_lookup_idx = -1;
					if (newNode.children[0].mdt_lookup_path && newNode.children[0].mdt_lookup_path.length > 0) {
						remove_lookup_idx = newNode.children[0].mdt_lookup_path.length - 1;
					}
					newNode.children = newNode.children[0].children;
					newNode = removeMdtLookupPath(newNode, remove_lookup_idx);
				}
				// no need to add this if the children is empty
				var children_show = false;
				for (var child_index in newNode.children) {
					var child_record = newNode.children[child_index];
					if ((child_record.is_sv && child_record.sv_show && child_record.sp_show) || child_record.show) {
						children_show = true;
						break;
					}
				}
				if (children_show || pac_mdt_data_exist || (newNode.other_span && mdt_data_exist)) {
					// calculate the span from its children
					var span_total = 0;
					var children_is_time_series = false;
					for (var child_index in newNode.children) {
						var child_record = newNode.children[child_index];					
						if ((child_record.is_sv && child_record.sv_show && child_record.sp_show) || (child_record.show)) {
							// special handling for child No CCYY TV
							if ((!child_record.is_sv) && (no_ccyy_tv.includes(child_record.class_var))) {
								var ccyy_lookup = $.grep(child_record.mdt_lookup_path, function (obj) { return (obj) && (obj.class_var == CCYY); });
								for (var ccyy_i in ccyy_lookup) {
									var temp_ccyy_record = ccyy_lookup[ccyy_i];
									if (child_record.class_code && table_data.ccyy_time_series_map[child_record.class_var][temp_ccyy_record.class_code][child_record.class_code].show) {
										span_total += child_record.span;
									} else if (!child_record.class_code && child_record.show) {	//total row / column
										span_total += child_record.span;
									}
								}							
							} else {
								span_total += child_record.span;
							}
						}
						if (!child_record.is_sv && table_data.lang_data.cv_list[child_record.class_var] && table_data.lang_data.cv_list[child_record.class_var].is_time_series == '1') {
							children_is_time_series = true;
						}
					}				
					// special handling for pac, where parent has no data
					if (pac_mdt_data_exist && (!newNode.children || newNode.children.length == 0)) {
						newNode.other_span = 1;
						for (var c_i = column_row_index + 1; c_i < column_row_array.length; c_i++) {
							var temp_record = column_row_array[c_i];
							if (temp_record.is_cv) {	// cv
								newNode.other_span++;
							} else {	// sv + sp, so 2 cells
								newNode.other_span += 2;
							}
						}
					}				
					newNode.span = span_total;
					newNode.mdt_data_exist = true;				
					// also update the original object
					temp_cell_record.mdt_data_exist = true;				
					// if need to show this record, then this span is at least 1
					var original_show = newNode.show;
					if (newNode.span == 0) {
						newNode.span = 1;
						if (newNode.class_var == CCYY) {
							newNode.show = false;
						}
					}				
					// if this cell is the same as last cell, then merge it instead of creating a new one
					if (last_cell_record && last_cell_record.class_var && last_cell_record.class_var == newNode.class_var && last_cell_record.class_code == newNode.class_code) {
						if (newNode.children && newNode.children.length > 0) {	// if the children is not empty
							if (newNode.other_span && last_cell_record.other_span) {
								last_cell_record.other_span = last_cell_record.other_span + newNode.other_span - 1;
							}
							if (newNode.children[0].escape_level) {
								newNode.children[0].escape_level += 1;
							} else {
								//newNode.children[0].escape_level = 1;
								newNode.children[0].escape_level = newNode.other_span ? newNode.other_span : 1;
							}
							result = newNode.children.reverse();
						} else {	// else children is empty
							var temp_other_span = newNode.other_span;
							if (temp_other_span) {
								temp_other_span++;
							} else {
								temp_other_span = 1;
							}						
							/*if (last_cell_record.other_span) {
								last_cell_record.other_span = temp_other_span;
							} else {*/
								last_cell_record.other_span = temp_other_span;
							/*}*/
						}
					} else if ((!newNode.is_sv && newNode.show) || (newNode.is_sv && (newNode.sp_show || newNode.sv_show))) {
						if (newNode.is_total) {
							if (result.length > 0) {
								var total_item = result.filter(function (f) { return f.is_total; })[0];
								if (!total_item) {
									result.push(newNode);
								} else {
									console.log("*** duplicated total item found");
									console.log(result);
									console.log(newNode);
								}
							} else {
								result.push(newNode);
							}
						} else {
							result.push(newNode);
						}						
					}/* else {	// for adding tv without CCYY
						if (newNode.is_tv && newNode.class_var === CCYY && !newNode.show && newNode.children) {
							if (checkCCYYChildrenShow(table_data, newNode)) {
								newNode.show = true;
								result.push(newNode);
							}
						}
					}*/
				}
			}				
		});
	}
	/* reverse the result back to the original*/
	result.reverse();
	result = orderingColumnRowTreeChildren(nexts, result, column_row_array);
	if (no_match_count === reverse_cell_list.length && result.length === 0) {
		result.all_no_match = true;
	}
	return result;
}

/*function checkCCYYChildrenShow(table_data, node) {
	if (node.children.filter(function (f) { return f.is_tv && f.show; }).length > 0) {
		var cc = table_data.cc_map.filter(function (f) { 
			return f.class_var === node.class_var && f.class_code_group === node.class_code_group && f.class_code === node.class_code;
		})[0];
		if (cc && cc.show && cc.has_data) {
			var check = $("#cc_" + cc.cc_index)[0].checked;
			if (!check) {
				return true;
			}
		}
	}
	return false;
}*/

function removeMdtLookupPath(newNode, idx) {
	if (newNode.children && idx > -1) {
		newNode.children.forEach(function (c) {
			if (c.mdt_lookup_path && c.mdt_lookup_path.length > idx) {
				c.mdt_lookup_path.splice(idx, 1);
			}
			c = removeMdtLookupPath(c, idx);
		});
	}
	return newNode;
}

function orderingColumnRowTreeChildren(nexts, result, column_row_array) {
	result = removeTVs(result, column_row_array);
	if (nexts && nexts.length > 1) {
		result.sort(function (a, b) {
			var class_var_a_idx = getColumnRowTreeChildrenIndex(a, column_row_array);
			var class_var_b_idx = getColumnRowTreeChildrenIndex(b, column_row_array);
			return class_var_a_idx - class_var_b_idx;
		});
	}
	return result;
}

function removeTVs(result, column_row_array) {
	if (result && result.length > 0 && column_row_array.filter(function (v) { return no_ccyy_tv.includes(v.class_var); })) {
		var no_ccyy = [];
		result.filter(function (v) { 
			return v.children && v.children.length > 0 && no_ccyy_tv.includes(v.children[0].class_var); 
		}).map(function (v) { 
			return v.children; 
		}).forEach(function (v) {
			no_ccyy = no_ccyy.concat(v);
		});
		no_ccyy.forEach(function (v) {
			if (v.other_span) {
				v.other_span++;
			} else {
				v.other_span = 2;
			}
		});
		var temp = result.filter(function (v) { 
			return !v.children || v.children.length === 0 || !no_ccyy_tv.includes(v.children[0].class_var);
		});
		if (temp.length === 0) {
			var min_other_span = finMaxValue(no_ccyy, "other_span", true);
			if (min_other_span >= 2) {
				min_other_span -= 1;
				no_ccyy.forEach(function (v) {
					if (v.other_span) {
						v.other_span -= min_other_span;
					}
					if (v.other_span === 1) {
						delete v.other_span;
					}
				});
			}
			if (result[0].is_tv) {
				result = temp.concat(no_ccyy);
			} else {
				if (result[0].children) {
					if (!result[0].children.filter(function (f) { return no_ccyy_tv.includes(f.class_var); })[0]) {
						result[0].children = no_ccyy;
					/*} else {
						console.log("*** remove no ccyy tv");*/
					}						
				}				
			}
		} else {
			result = temp.concat(no_ccyy);
		}		
	}
	return result;
}

function getColumnRowTreeChildrenIndex(obj, column_row_array) {
	var class_var = obj.class_var;
	var tv = column_row_array.filter(function (i) { return i.is_tv && i.class_var === class_var; })[0];
	if (obj.children && obj.children.length > 0) {
		class_var = obj.children[0].class_var ? obj.children[0].class_var : class_var;
		var temp = column_row_array.filter(function (i) { return i.is_tv && i.class_var === class_var; })[0];
		if (temp) {
			tv = temp;
		}
	}
	if (tv) {
		return tv.tv_display_seq;
	}
	return -999;
	//return  column_row_array.filter(function (i) { return i.is_tv && i.class_var === class_var; })[0];
}

function checkMdtExists(table_data, cell_record, column_row_array, original_mdt, mdt_data_exist, is_pac) {
	if (is_pac) {
		var remains = [];
		if (cell_record.is_sv) {
			remains = column_row_array.filter(function (v) { return v.is_cv; });
		} else {
			remains = column_row_array.filter(function (v) { return v.class_var !== cell_record.class_var; });
		}
		if (remains.length === column_row_array.length) {
			return false; //not PAC
		}
		if (!cell_record.is_total && (!cell_record.pac || cell_record.pac.length === 0)) {
			if (cell_record.class_var) {	//pac child item could be hidden for grid mode
				var pacs = table_data.lang_data.cv_list[cell_record.class_var].pac_list;
				if (pacs && pacs.length > 0) {
					var pac = pacs.filter(function (f) { 
						return (f.parent_class_code_group === cell_record.class_code_group && f.parent_class_code === cell_record.class_code) ||
							(f.child_class_code_group === cell_record.class_code_group && f.child_class_code === cell_record.class_code);
					});
					if (pac.length === 0) {
						return false;
					}					
				} else {
					return false;
				}
			} else {
				return false;
			}
		}
	}
	var sv = cell_record.mdt_lookup_path.filter(function (v) { return v.is_sv; })[0];
	if (sv) {
		var mdt = original_mdt[sv.stat_var][sv.stat_pres];
		if (is_pac || column_row_array.filter(function (v) { return v.is_tv; }).length > 0) {
			column_row_array.forEach(function (v) {
				if (v.class_var && cell_record.mdt_lookup_path.filter(function (m) { return m.stat_var === v.class_var || m.class_var === v.class_var; }).length <= 0) {
					mdt = mdt.filter(function (m) { return !m[v.class_var]; });
				}
			});
		}
		return mdt && mdt.length > 0;
	} else {
		for (var sv1 in original_mdt) {
			for (var sp in original_mdt[sv1]) {
				var mdt = original_mdt[sv1][sp];
				if (mdt && mdt.length > 0) {
					if (is_pac || column_row_array.filter(function (v) { return v.is_tv; }).length > 0) {
						column_row_array.forEach(function (v) {
							if (v.class_var && cell_record.mdt_lookup_path.filter(function (m) { return m.stat_var === v.class_var || m.class_var === v.class_var; }).length <= 0) {
								mdt = mdt.filter(function (m) { return !m[v.class_var]; });
							}
						});
					}
				}
				if (mdt && mdt.length > 0) {
					return true;
				}					
			}
		}		
		mdt_data_exist = false;
	}
	return mdt_data_exist;	
}

function checkMdtExistsForRowColumnValues(table_data, class_var, class_code) {
	for (var sv in table_data.mdt_data) {
		for (var sp in table_data.mdt_data[sv]) {
			var mdt = table_data.mdt_data[sv][sp];
			if (mdt.filter(function (v) { return v[class_var] === class_code; })[0]) {
				return true;
			}
		}
	}
	return false;
}

function getLeafNodes(column_row, level, is_row) {
	var result = [];
	column_row.forEach(function (cr) {
		if (cr.show || cr.sv_show || cr.sp_show) {
			cr.is_row = is_row;
			if (cr.children && cr.children.length > 0) {
				cr.is_leaf = false;
				cr.level = level + (cr.other_span ? cr.other_span - 1 : 0);
				result.push(cr);
				result = result.concat(getLeafNodes(cr.children, cr.level + 1, is_row));
			} else {
				cr.level = level + (cr.other_span ? cr.other_span - 1 : 0);
				cr.is_leaf = true;
				result.push(cr);
			}
		}
	});
	return result;
}

function resetGroupSDValues(node, sd) {
	if (node.group_sd_value && sd !== "") {
		node.sd_value_array = node.sd_value_array.filter(function (v) { return v !== sd; });
		node.sd_values = node.sd_value_array.join(",");
	} else {
		node.sd_value_array = [];
		node.sd_values = "";
	}
	if (node.children) {
		node.children.forEach(function (c) {
			resetGroupSDValues(c, sd);
		})
	}
}

function clearTempIgnoreSDValues(sv_list) {
	sv_list.forEach(function (sv) {
		sv.mdt.filter(function (f) {
			return f.tmp_ignore_sd_values && f.tmp_ignore_sd_values.length > 0;
		}).forEach(function (m) {
			delete m.tmp_ignore_sd_values;
		});
	});
}

function groupSDValues(table_data, all_cvs, sv_list, rows, columns) {
	var row_group_cv, column_group_cv;
	var allowed_tv = [];	
	var groups = all_cvs.filter(function (f) { return table_data.lang_data.cv_list[f].group_sd_value === "1"; });
	groups.forEach(function (cv) {
		var obj = table_data.component_data.table_component_ccg_list[cv];
		var is_tv = table_data.lang_data.cv_list[cv].is_time_series === "1";
		var tmp = {
			class_var: is_tv ? tv_name : cv,
			is_tv: is_tv,
			order: parseInt(obj.display_order)
		}
		if (is_tv) {
			allowed_tv.push(cv);
		}
		if (parseInt(obj.cv_position) === 0) {	//row
			if (!row_group_cv || row_group_cv.order < tmp.order) {
				row_group_cv = tmp
			}
		} else if (parseInt(obj.cv_position) === 1) {	//column
			if (!column_group_cv || column_group_cv.order < tmp.order) {
				column_group_cv = tmp
			}
		}
	});
	if (row_group_cv) {
		groupSDValuesByArea(table_data, all_cvs, sv_list, rows, columns.filter(function (f) { return f.is_leaf && (f.show || f.sv_show || f.sp_show); }), row_group_cv.class_var, allowed_tv);
	}
	if (column_group_cv) {
		groupSDValuesByArea(table_data, all_cvs, sv_list, columns, rows.filter(function (f) { return f.is_leaf && (f.show || f.sv_show || f.sp_show); }), column_group_cv.class_var, allowed_tv);
	}
}

function groupSDValuesByArea(table_data, all_cvs, sv_list, targets, others, cv, allowed_tv) {
	var objs = targets.filter(function (f) { 
		var result = f.show || f.sv_show || f.sp_shpw;
		if (cv === tv_name) {
			return result && f.is_tv && allowed_tv.includes(f.class_var);
		} else {
			return result && f.class_var === cv; 
		}
	}).sort(function (a, b) {
		if (a.level <= b.level) {
			return 1;
		} else {
			return -1;
		}
	});
	if (objs && objs.length > 0) {
		if (cv !== tv_name) {
			var cv_lang = table_data.lang_data.cv_list[cv];
			if (cv_lang.pac_list && cv_lang.pac_list.length > 0) {
				var max_level = finMaxValue(objs, "level");
				objs = objs.filter(function (f) { return f.level === max_level; });
			}
		}		
		objs.forEach(function (tgt) {
			var errorFound = false;
			var mdt = [];
			if (!errorFound) {
				others.forEach(function (oth) {
					if (!errorFound) {
						var filter_list = [];
						if (tgt.children) {	//objs children to be checked
							filter_list = findChildFiltering(tgt);
						} else {
							filter_list.push(tgt.mdt_lookup_path);
						}				
						filter_list.forEach(function (flt) {							
							var temp_mdt = [];
							var filters = flt.concat(oth.mdt_lookup_path);
							var svs = filters.filter(function (f) { return f.is_sv });	//sv ignore mdt grep
							filters = filters.filter(function (f) { return !f.ignore_mdt_grep; });
							if (svs && svs.length > 0) {
								svs.forEach(function (sv) {
									var not_used_cv = all_cvs.slice(0);
									var temp_obj = sv_list.filter(function (f) { return f.stat_var === sv.stat_var && f.stat_pres === sv.stat_pres; })[0];
									if (temp_obj) {
										temp_mdt = temp_obj.mdt;
										filters.filter(function (f) { return !f.ignore_mdt_grep; }).forEach(function (ft) {
											if (ft.class_code) {
												temp_mdt = temp_mdt.filter(function (f) { return f[ft.class_var] == ft.class_code; });
											} else {
												temp_mdt = temp_mdt.filter(function (f) { return !f[ft.class_var] || f[ft.class_var] == ft.class_code; });
											}
											not_used_cv = not_used_cv.filter(function (f) { return f !== ft.class_var; });
										});
										if (not_used_cv.length > 0) {
											not_used_cv.forEach(function (n) {
												temp_mdt = temp_mdt.filter(function (f) { return !f[n]; });
											});
										}
										if (temp_mdt && temp_mdt.length >= 1) {
											if (temp_mdt.length === 1) {
												mdt.push(temp_mdt[0]);
											} else {
												errorFound = true;
												errorLog("groupSDValuesByArea", "more than 1 data found");
											}
										} else if (!temp_mdt || temp_mdt.length === 0) {
											errorFound = true;
										}
									} else {
										errorFound = true;
										errorLog("groupSDValuesByArea", "mdt not found");
									}
								});
							}
						});
					}
				});
			}
			if (mdt && mdt.length > 0 && !errorFound) {
				if (mdt[0].sd_value) {
					var sd_values = mdt[0].sd_value.split(",");
					sd_values.forEach(function (sd) {
						if (all_sd_list[sd] && all_sd_list[sd].obs_value_suppressed !== '1') {	//suppressed notes will not be grouped
							var sd_mdt = mdt.filter(function (f) {
								if (!f.sd_value) {
									return false;
								} else {
									return f.sd_value.split(",").includes(sd);
								}
							});
							if (sd_mdt.length === mdt.length) {
								mdt.forEach(function (v) {
									if (!v.ignore_sd_values) {
										v.ignore_sd_values = [];
									}
									if (!v.ignore_sd_values.includes(sd)) {
										v.ignore_sd_values.push(sd);
									}
								});
								tgt.sd_value_array.push(sd);
								tgt.sd_values = tgt.sd_value_array.join(",");
							}
						}						
					});
				}
			}
		});
	}
}

function findChildFiltering(obj) {
	var result = [];
	if (obj.children && obj.children.length > 0) {
		obj.children.forEach(function (c) {
			var temp = findChildFiltering(c);
			if (temp && temp.length > 0) {
				result = result.concat(temp);
			}
		});
	} else {
		result.push(obj.mdt_lookup_path);
		return result;
	}
	return result;
}

//for group sd_values one level (excepts for sv & sp)
function checkMdtExistsAfterColumnRowArrayBuilt(all_cvs, targets, others, sv_list, target_all, gourp_sd_value_flag, is_first) {
	targets.forEach(function (t) {
		if (t.children && t.children.length > 0) {
			t.children = checkMdtExistsAfterColumnRowArrayBuilt(all_cvs, t.children, others, sv_list, target_all, t.group_sd_value || gourp_sd_value_flag, false);
			t.children = $.grep(t.children, function (v) { return (v.is_sv && (v.sv_show || v.sp_show)) || (!v.is_sv && v.show); });
			t.span = 0;
			t.children.forEach(function (v) {
				t.span += v.span;
			});
			if (t.children.length === 0) {
				if (t.is_sv) {
					if (t.sv_show) {
						t.sv_show = false;
					}
					if (t.sp_show) {
						t.sp_show = false;
					}
				} else {
					t.show = false;
				}				
			}
			t.span = Math.max(t.span, 1);
			t.sd_value_array = [];
			t.sd_values = "";
			/*if (t.children.length > 0 && (gourp_sd_value_flag || t.group_sd_value)) {
				var sd_flag = t.children[0].sd_flag;
				if (sd_flag) {
					gourp_sd_value_flag = false;
					sv_list.forEach(function (sv) {
						sv.mdt.filter(function (f) {
							return f.tmp_ignore_sd_values && f.tmp_ignore_sd_values.length > 0;
						}).forEach(function (m) {
							if (!m.ignore_sd_values || m.ignore_sd_values.length === 0) {
								m.ignore_sd_values = clone(m.tmp_ignore_sd_values);
							} else {
								m.ignore_sd_values = m.ignore_sd_values.concat(m.tmp_ignore_sd_values);
							}
							delete m.tmp_ignore_sd_values;
						});
					});
					t.sd_flag = true;
				} else {
					if (!sd_flag || t.group_sd_value) {						
						t.children[0].sd_value_array.forEach(function (sd) {
							if (t.children.filter(function (c) { return !c.sd_value_array.includes(sd); }).length <= 0) {
								t.sd_value_array.push(sd);
							}
						});
						t.sd_values = t.sd_value_array.join(",");
						if (t.group_sd_value) {
							t.sd_flag = true;
						}
						t.sd_value_array.forEach(function (sd) {
							t.children.forEach(function (c) {
								resetGroupSDValues(c, sd);
							});
							if (t.sd_flag) {
								sv_list.forEach(function (sv) {
									sv.mdt.filter(function (f) {
										return f.tmp_ignore_sd_values && f.tmp_ignore_sd_values.length > 0;
									}).forEach(function (m) {
										if (m.tmp_ignore_sd_values.includes(sd)) {
											if (!m.ignore_sd_values) {
												m.ignore_sd_values = [];
											}
											if (!m.ignore_sd_values.includes(sd)) {
												m.ignore_sd_values.push(sd);
											}
										}
									});
								});
							}
						});
						if (t.sd_value_array.length === 0) {
							t.children.forEach(function (c) {
								resetGroupSDValues(c, "");
							});
						}
					}
				}
			} else if (t.children.length > 0 && t.children[0].sd_flag && t.children[0].group_sd_value) {
				gourp_sd_value_flag = false;
				sv_list.forEach(function (sv) {
					sv.mdt.filter(function (f) {
						return f.tmp_ignore_sd_values && f.tmp_ignore_sd_values.length > 0;
					}).forEach(function (m) {
						if (!m.ignore_sd_values || m.ignore_sd_values.length === 0) {
							m.ignore_sd_values = clone(m.tmp_ignore_sd_values);
						} else {
							m.ignore_sd_values = m.ignore_sd_values.concat(m.tmp_ignore_sd_values);
						}
						delete m.tmp_ignore_sd_values;
					});
				});
				t.sd_flag = true;
			}
			if (t.sd_flag) {
				clearTempIgnoreSDValues(sv_list);
			}*/
		} else {
			var found = false;
			var target_mdt = [];			
			for (var i = 0; i < others.length; i++) {
				var filters = others[i].mdt_lookup_path.concat(t.mdt_lookup_path);
				var sv_node = $.grep(filters, function (v) { return v.is_sv; })[0];
				//var sv_node = filters.filter(function (v) { return v.is_sv; })[0];
				if (sv_node) {
					var temp = $.grep(sv_list, function (v) { return v.stat_var === sv_node.stat_var && v.stat_pres === sv_node.stat_pres; })[0];
					filters = $.grep(filters, function (v) { return !v.is_sv; });
					var excludes =  $.grep(target_all, function (v) { return !v.is_sv && v.class_var !== t.class_var; });
					/*var temp = sv_list.filter(function (v) { return v.stat_var === sv_node.stat_var && v.stat_pres === sv_node.stat_pres; })[0];
					filters = filters.filter(function (v) { return !v.is_sv; });
					var excludes = target_all.filter(function (v) { return !v.is_sv && v.class_var !== t.class_var; });*/
					if (temp && filters.length > 0) {
						var mdt = temp.mdt;
						var fields = all_cvs.slice(0);
						$.grep(filters, function (v) { return !v.ignore_mdt_grep; }).forEach(function (f) {
							if (f.class_code) {
								mdt = $.grep(mdt, function (m) { return m[f.class_var] == f.class_code; });
							} else {
								mdt = $.grep(mdt, function (m) { return !m[f.class_var] || m[f.class_var] == f.class_code; });
							}
							fields = $.grep(fields, function (fld) { return fld !== f.class_var; });
							excludes = $.grep(excludes, function (v) { return v.class_var !== f.class_var; });
						});
						/*filters.filter(function (v) { return !v.ignore_mdt_grep; }).forEach(function (f) {
							if (f.class_code) {
								mdt = mdt.filter(function (m) { return m[f.class_var] == f.class_code; });
							} else {
								mdt = mdt.filter(function (m) { return !m[f.class_var] || m[f.class_var] == f.class_code; });
							}
							fields = fields.filter(function (fld) { return fld !== f.class_var; });
							excludes = excludes.filter(function (v) { return v.class_var !== f.class_var; });
						});*/
						excludes.forEach(function (e) {
							mdt = $.grep(mdt, function (f) { return !f[e.class_var]; });
							fields = $.grep(fields, function (f) { return f !== e.class_var; });
						});
						if (fields && fields.length > 0) {	//MDT properties not used in current filtering
							fields.forEach(function (fld) {
								mdt = $.grep(mdt, function (f) { return !f[fld]; });
							});
						}
						if (mdt && mdt.length > 0) {
							found = true;
							/*if (mdt[0].sd_value) {
								target_mdt = target_mdt.concat(mdt);
							} else {
								target_mdt = [];
								break;
							}*/
							break;
						}
					}
				}
				if (i === others.length - 1 && !found) {
					if (t.is_sv) {
						if (t.sv_show) {
							t.sv_show = false;
						}
						if (t.sp_show) {
							t.sp_show = false;
						}
					} else {
						t.show = false;
					}
					console.log("*** remove: ");
					console.log(t);
				}
			}
			t.sd_value_array = [];
			t.sd_values = "";
			/*if (target_mdt.length > 0 && (t.group_sd_value || gourp_sd_value_flag)) {
				if (target_mdt[0].sd_value) {
					if (t.group_sd_value) {
						t.sd_flag = true;
					}
					var sds = target_mdt[0].sd_value.split(",");
					sds.forEach(function (sd) {
						if (all_sd_list[sd] && all_sd_list[sd].obs_value_suppressed !== '1') {	//suppressed notes will not be grouped
							if (target_mdt.filter(function (v) { return !v.sd_value.split(",").includes(sd); }).length <= 0) {
								t.sd_value_array.push(sd);
							}
						}
					});
					t.sd_values = t.sd_value_array.join(",");
					if (t.sd_value_array.length > 0) {
						target_mdt.forEach(function (m) {
							if (is_first) {
								if (!m.ignore_sd_values) {
									m.ignore_sd_values = [];
								}
								t.sd_value_array.forEach(function (sd) {
									if (!m.ignore_sd_values.includes(sd)) {
										m.ignore_sd_values.push(sd);
									}													
								});
							} else {
								if (!m.tmp_ignore_sd_values) {
									m.tmp_ignore_sd_values = [];
								}
								t.sd_value_array.forEach(function (sd) {
									if (!m.tmp_ignore_sd_values.includes(sd)) {
										m.tmp_ignore_sd_values.push(sd);
									}													
								});	
							}
						});
					}
				}
			}*/
		}
	});
	return targets;
}

function getNextNodeIdx(cell_record, column_row_array, idx) {	//-999: span = 1, -9999: calculate the new span
	var result = [];
	if (idx === column_row_array.length - 1) {
		result.push(-999);
		return result;
	}
	if (!cell_record.is_tv) {
		result.push(idx + 1);
		var nextNode = column_row_array[idx + 1];
		if (nextNode.is_tv) {
			column_row_array.filter(function (v) { return indenpendent_tv_list.includes(v.class_var) && v.class_var !== nextNode.class_var; }).forEach(function (v) {
				result.push(column_row_array.indexOf(v));
			});
		}
		return result;
	}	
	var tv_counts = cell_record.mdt_lookup_path.filter(function (v) { return v.is_tv; }).map(function (v) { return v.class_var; });
	var remains = [];
	var indepent = indenpendent_tv_list.includes(cell_record.class_var);
	if (idx >= 0) {
		remains = column_row_array.slice(idx + 1);
	}
	if (!indepent) {
		remains = remains.filter(function (v) { return !v.is_tv; });
		if (remains && remains.length > 0) {
			result.push(column_row_array.indexOf(remains[0]));
		} else {
			result = result.reverse();
			result.push(-999);
		}
	} else { 
		if (cell_record.class_var === CCYY) {
			remains = remains.filter(function (v) { return v.is_tv && !indenpendent_tv_list.includes(v.class_var); });
			remains.forEach(function (r) {
				result.push(column_row_array.indexOf(r));
			});
		}
	}
	result = result.reverse();
	if (indepent) {	//leaf node
		remains = column_row_array.slice(idx + 1).filter(function (v) { return !v.is_tv; });
		var next = null;
		if (remains.length > 0) {
			next = column_row_array.indexOf(remains[0]) * (-1);
		}
		if (cell_record.class_var === CCYY) {
			if (cell_record.tv_display_seq > 0) {
				if (result.length > 0) {
					result.push(next ? next - 1000 : -9999);	//for calculate the span
				} else {
					result.push(next ? next - 100 : -999);
				}
			}
		} else {
			var tvs = column_row_array.filter(function (v) { return v.is_tv && !indenpendent_tv_list.includes(v.class_var) && !no_ccyy_tv.includes(v.class_var); });
			if (tvs.length > 0) {
				result.push(next ? next - 1000 : -9999);	//for calculate the span
			} else {
				result.push(next ? next - 100 : -999);
			}
		}
	}
	if (result.filter(function (v) { return v === -1; }).length > 0) {
		console.log("recursive column row header error occurred");
	}
	return result;
}

function checkMdtSdValueList(mdt_record_list, new_sd_value_array) {
	for (var temp_mdt_index = 1; temp_mdt_index < mdt_record_list.length; temp_mdt_index++) {
		if (mdt_record_list[temp_mdt_index].sd_value) {
			var temp_mdt_sd_array = mdt_record_list[temp_mdt_index].sd_value.split(',');
			temp_mdt_sd_array.sort();
			new_sd_value_array = intersect_safe(new_sd_value_array, temp_mdt_sd_array);
			if (new_sd_value_array.length == 0) {
				break;
			}
		} else {
			// no sd value for this mdt record, so no grouping
			new_sd_value_array = [];
			break;
		}
	}
	return new_sd_value_array;
}

function removeMdtLookup(cell_record, class_var) {	
	for (var c_i = 0; c_i < cell_record.children.length; c_i++) {
		var child_record = cell_record.children[c_i];
		for (var t_i = 0; t_i < child_record.mdt_lookup_path.length; t_i++) {
			var lookup_record = child_record.mdt_lookup_path[t_i];
			if (lookup_record.class_var == class_var) {
				// delete next record
				delete child_record.mdt_lookup_path[t_i + 1];
				break;
			}
		}
		removeMdtLookup(child_record, class_var);
	}	
}

function getPeriodStartEnd(hdr) {
	var result = [];
	var year = 0;
	hdr.mdt_lookup_path.filter(function (v) { return !v.is_sv && v.is_tv; }).forEach(function (v) {
		var val = parseInt(v.class_code);
		switch (v.class_var) {
			case CCYY:
				year = val * 100;
				break;
			case CCYY_F:
				result = [ val * 100 + 4, (val + 1) * 100 + 3 ];
				//year = val * 100;
				break;
			case H:				
				result = [ year + ((val - 1) * 6 + 1), year + (val * 6) ];
				break;
			case Q:
				result = [ year + ((val - 1) * 3 + 1), year + (val * 3) ];
				break;
			default:
				result = [ year + val, year + val ];
				break;
		}
	});
	if (result.length === 0 && year > 0) {
		result = [ year / 100, year / 100];
	}
	return result;
}

function generateNotesRow(notes_element, row_counter, col_1_text, notes_data, skipHtml) {
	if (col_1_text) {
		row_counter++;
		if (!skipHtml) {
			var div_element = document.createElement("div");
			div_element.innerHTML = col_1_text;
			notes_element.appendChild(div_element);		
		}
		col_1_text.split("</p>").forEach(function (v) {
			var txt = v.replaceAll("\r", "").replaceAll("\n", "").replaceAll("<br />", "").replaceAll("<br>", "").replaceAll("&nbsp;", "");
			var startTag = ""
			var startTagIdx = Math.min(txt.indexOf(">"), txt.indexOf(" "));
			var endTag = "";
			if (startTagIdx >= 0) {
				startTag = txt.substring(0, startTagIdx) + ">";
			}
			if (!txt.endsWith(">")) {
				if (startTag) {
					endTag = startTag.replace("<", "</");
					txt = txt + endTag;
				} else {
					txt = "<span>" + txt + "</span>";
				}
			}
			if ($(txt).text() !== "") {
				v += endTag;
				notes_data.push([v]);
			}
			/*if (v.replaceAll("<p>", "").replaceAll("\r", "").replaceAll("\n", "").replaceAll("<br />", "").replaceAll("<br>", "").replaceAll("&nbsp;", "") !== "") {
				v += "</p>";
				notes_data.push([v]);
			}*/
		});		
	}
	return row_counter;
}

function getTableListOrder(table_id) {
	if (table_id_list && table_id_list.indexOf(table_id) >= 0){
		return table_id_list.indexOf(table_id);
	} else {
		return null;
	}
}

function addHiddenNotes(table_data, span, table) {
	if (table_data.notes_data_export && table_data.notes_data_export.length > 0) {
		$(table).find("tbody").append("<tr class='hiddentrforExport'><td class='hiddentdforExport' colspan='" + span + "' style='" + exportTableCellStyle + "'>&nbsp;</td></tr>");
		var notes_added = false;
		(table_data.notes_data_export || [[]]).forEach(function (notes) {
			if (notes && notes.length > 0) {
				var txt = setNotesContextForExport(notes.filter(function (f) { return f !== "SD_VALUE"; }));
				if (txt) {
					if (!notes_added) {
						notes_added = true;
						$(table).find("tbody").append("<tr class='hiddentrforExport'><td class='hiddentdforExport' data-t='s' colspan='" + span + "' style='" + exportTableCellStyle + "'>" + table_text.notes + "</td></tr>");
					}
					$(table).find("tbody").append("<tr class='hiddentrforExport'><td class='hiddentdforExport' data-t='s' colspan='" + span + "' style='" + exportTableCellStyle + "'>" + txt + "</td></tr>");
				}
			}
		});
	}
	var source_added = false;
	(table_data.source_data || [[]]).forEach(function (src) {
		if (src && src.length > 0) {				
			var txt = setNotesContextForExport(src);
			if (txt) {
				if (!source_added) {
					source_added = true;
					$(table).find("tbody").append("<tr class='hiddentrforExport'><td class='hiddentdforExport' colspan='" + span + "' style='" + exportTableCellStyle + "'>&nbsp;</td></tr>");
					$(table).find("tbody").append("<tr class='hiddentrforExport'><td class='hiddentdforExport' data-t='s' colspan='" + span + "' style='" + exportTableCellStyle + "'>" + table_text.source + "</td></tr>");
				}
				$(table).find("tbody").append("<tr class='hiddentrforExport'><td class='hiddentdforExport' data-t='s' colspan='" + span + "' style='" + exportTableCellStyle + "'>" + txt + "</td></tr>");
			}
		}
	});
	$(table).find("tbody").append("<tr class='hiddentrforExport exclude_sd_values'><td class='hiddentdforExport' colspan='" + span + "' style='" + exportTableCellStyle + "'>&nbsp;</td></tr>");
	$(table).find("tbody").append("<tr class='hiddentrforExport exclude_sd_values'><td class='hiddentdforExport' data-t='s' colspan='" + span + "' style='" + exportTableCellStyle + "'>" + down_text.csv.remark + "</td></tr>");
	$(table).find("tbody").append("<tr class='hiddentrforExport exclude_sd_values'><td class='hiddentdforExport' data-t='s' colspan='" + span + "' style='" + exportTableCellStyle + "'><span>" + down_text.csv.remark2 + "</span></td></tr>");	
	var vDate = $("#last_revision_date")[0]
	if (vDate) {
		$(table).find("tbody").append("<tr class='hiddentrforExport'><td class='hiddentdforExport' colspan='" + span + "' style='" + exportTableCellStyle + "'>&nbsp;</td></tr>");
		$(table).find("tbody").append("<tr class='hiddentrforExport'><td class='hiddentdforExport' data-t='s' colspan='" + span + "' style='" + exportTableCellStyle + "'>" + date_time_string.release_date + $(vDate).html() + "</td></tr>");
	}
}

function setNotesContextForExport(src) {
	var result = src.join(" ").replaceAll("\r\n", "");
	if (result === "\r") {
		return "";
	} else {
		var temp = result.replaceAll("<p>", "").replaceAll("</p>", "").replaceAll("\r", "");
		if (temp.trim() === "") {
			return "";
		}
		result = result.replaceAll("<p>", "<span data-t='s'>").replaceAll("<p ", "<span data-t='s' ").replaceAll("</p>", "</span>");
	}
	if (result.endsWith("\r")) {
		result = result.substring(0, result.length - "\r".length);
	}
	return result;
}

function createNotesArray(notes, notes_array_simple, notes_array, no_sd_value) {
	for (var n_index in notes) {
		var note_row = notes[n_index];
		var note_test_array = [];
		var has_sd_value = false;
		for (var r_index in note_row) {
			var note_cell = note_row[r_index];
			if (note_cell == 'SD_VALUE') {
				has_sd_value = true;
				continue;
			}
			var div = document.createElement("div");
			div.innerHTML = note_cell;
			var note_text = div.textContent || div.innerText || "";
			note_text = note_text.trim();
			note_test_array.push(note_text);
		}		
		var simple_note_text = note_test_array.join(' ');
		if (simple_note_text) {
			if (note_test_array.length === 1 || notes_array_simple.indexOf(simple_note_text) < 0) {
				notes_array.push([simple_note_text]);
				notes_array_simple.push(simple_note_text);
			}
		}
	}
}

function getSubjectCodes(table_data) {
	var scodes = [];
	if (table_data.lang_data.subject_list) {
		table_data.lang_data.subject_list.forEach(function (v) {
			if (!$.grep(scodes, function (f) { return f.subject === v.Subject_Code; })[0]) {
				scodes.push({
					subject: v.Subject_Code,
					primary: v.Primary_Subject === "1"
				});
			}
		});
	}
	scodes = scodes.sort(function (a, b) {
		if (a.primary) {
			return -1;
		} else if (b.primary) {
			return 1;
		} else {
			if (a.subject <= b.subject) {
				return -1;
			}
			return 1;
		}
	});
	return scodes;
}

function mapNotesWithSubjects(subjects) {
	var s = subjects.map(function (m) { return m.subject; }).sort(function (a, b) {
		if (a <= b) {
			return -1;
		}
		return 1;
	});
	return s.join(",");
}

function getNotesItem(table_data, notes, note_type) {
	var subjects = mapNotesWithSubjects(getSubjectCodes(table_data));
	var result = note_data_array.filter(function (v) { 
		var result = v.note_type === note_type && v.notes === notes;
		if (note_type === 'sd_value') {
			result = result;// && v.table_id === table_data.table_id;
		} else {
			result = result && mapNotesWithSubjects(v.subjects) === subjects && v.notes === notes;
		}
		return result;
	})[0];
	return result;
}

function getSourceItem(table_data) {
	var subjects = mapNotesWithSubjects(getSubjectCodes(table_data));
	return source_data_array.filter(function (v) { 
		return mapNotesWithSubjects(v.subjects) === subjects && v.notes === table_data.lang_data.tb_src;
	})[0];
}

function generateNotes(table_data, keep_note) {
	if (typeof default_demographics_lookup_path !== 'undefined') {
		generateNotesForMap(table_data);
		return;
	}
	var i, j;
	var notes_element = document.getElementById(table_notes);
	var source_element = document.getElementById('table_source');
	table_data.notes_data = [];
	table_data.source_data = [];	
	var table_notes_element = document.getElementById(table_data.table_id + '_' + table_notes);
	var add_note_data_array = true;
	var add_table_id_to_sd_symbol = false;
	var table_order = null;
	if (table_notes_element) {
		notes_element = table_notes_element;
		add_note_data_array = false;
		add_table_id_to_sd_symbol = true;
		table_order = getTableListOrder(table_data.table_id) + 1;
	}	
	if (notes_element) {
		var row_counter = 0;		
		// delete original data
		if (!keep_note) {
			notes_element.innerHTML = '';
			note_data_array = [];
		}		
		var footnote_text = '';		
		if (add_note_data_array) {
			if (note_data_array.indexOf(table_data.lang_data.tb_fn) < 0) {
				row_counter = generateNotesRow(notes_element, row_counter, table_data.lang_data.tb_fn, table_data.notes_data);
				note_data_array.push(table_data.lang_data.tb_fn);
			}
		} else {
			row_counter = generateNotesRow(notes_element, row_counter, table_data.lang_data.tb_fn, table_data.notes_data);
		}		
		// insert CV / CC / SV / SP footnotes
		for (i = 0; i < table_data.footnote_used_list.length; i++) {
			var note_string = table_data.footnote_used_list[i];
			var note_counter = i + 1;			
			var cell_counter = 0;
			row_counter++;			
			var div_element = document.createElement("div");
			div_element.classList.add('note_row');
			div_element.classList.add('footnote_lnks');			
			notes_element.appendChild(div_element);
			var div_element_1 = document.createElement("div");
			div_element_1.classList.add('sd_td');
			if (add_table_id_to_sd_symbol && table_order) {				
				var table_order_footnote_index = table_data.table_id + '_' + note_counter;
				var table_order_footnote_index_id = 'cdm_footnote_text_' + table_order_footnote_index_id_counter;				
				var table_order_footnote_index_obj;
				if (table_order_footnote_index_map[table_order_footnote_index]) {
					table_order_footnote_index_obj = table_order_footnote_index_map[table_order_footnote_index];
				} else {
					table_order_footnote_index_obj = {
						table_order_footnote_index_id: [],
						table_order_footnote_index_number: null,
						table_order_footnote_index_text: null
					};
					table_order_footnote_index_map[table_order_footnote_index] = table_order_footnote_index_obj;
				}
				table_order_footnote_index_map[table_order_footnote_index].table_order_footnote_index_text = table_order_footnote_index_id;
				table_order_footnote_index_id_counter++;				
				div_element_1.innerHTML = '<a name="' + table_order_footnote_index + '" id="' + table_order_footnote_index_id + '" style="text-decoration: none;">' + note_counter + '</a>';
			} else {
				if (((typeof(idds) != 'undefined') && (idds)) || ((typeof(census21) != 'undefined') && (census21))) {
					div_element_1.innerHTML = '<a name="' + (table_data ? table_data.table_id + "_" : "") + note_counter + '" style="text-decoration: none;">(' + note_counter + ')</a>';
				} else {
					div_element_1.innerHTML = '<a name="' + (table_data ? table_data.table_id + "_" : "") + note_counter + '" style="text-decoration: none;">' + note_counter + '</a>';
				}
			}
			div_element.appendChild(div_element_1);			
			var div_element_2 = document.createElement("div");
			div_element_2.classList.add('note_row_detail');
			div_element_2.innerHTML = note_string;
			div_element.appendChild(div_element_2);			
			var note_row = [note_counter, note_string];
			if (((typeof(idds) != 'undefined') && (idds)) || ((typeof(census21) != 'undefined') && (census21))) {
				note_row = ['(' + note_counter + ')', note_string];
			}
			table_data.notes_data.push(note_row);
		}		
		// insert sd value notes
		for (i = 0; i < table_data.sd_used_list.length; i++) {
			var sd_value = table_data.sd_used_list[i];
			if (sd_value == 0) {
				continue;
			}
			var sd = table_data.sd_list[sd_value];
			var sd_desc = sd.sd_desc;
			var sd_sybmol = sd.sd_symbol;
			if ((add_note_data_array && note_data_array.indexOf(sd_sybmol) < 0) || !add_note_data_array) {
				var cell_counter = 0;
				row_counter++;
				var div_element = document.createElement("div");
				div_element.classList.add('note_row');
				div_element.classList.add("footnote_lnks");
				notes_element.appendChild(div_element);
				var div_element_1 = document.createElement("div");
				div_element_1.classList.add('sd_td');				
				if (add_table_id_to_sd_symbol) {
					div_element_1.innerHTML = '<a name="' + table_data.table_id + '_' + sd_sybmol + '" style="text-decoration: none;">' + sd_sybmol + '</a>';
				} else {
					div_element_1.innerHTML = '<a name="' + table_data.table_id + '_' + sd_sybmol + '" style="text-decoration: none;">' + sd_sybmol + '</a>';
				}
				div_element.appendChild(div_element_1);				
				var div_element_2 = document.createElement("div");
				div_element_2.classList.add('note_row_detail');
				div_element_2.innerHTML = sd_desc;
				div_element.appendChild(div_element_2);
				var note_row = [sd_sybmol, sd_desc, 'SD_VALUE'];
				table_data.notes_data.push(note_row);				
				if (add_note_data_array) {
					note_data_array.push(sd_sybmol);
				}
			}
		}
		if ((table_data.notes_data.length == 0) && (!keep_note)) {
			$("#notes_header").hide();
			$("#notes").hide();
		} else {
			$("#notes_header").show();
			$("#notes").show();
		}
	}	
	table_data.notes_data_export = clone(table_data.notes_data);
	if (source_element) {
		table_data.source_data.push([]);
		var row_counter = 0;
		// delete original data
		if (table_data.lang_data.tb_src) {
			source_element.innerHTML = '';
		}
		row_counter = generateNotesRow(source_element, row_counter, table_data.lang_data.tb_src, table_data.source_data);
	}
	/*if (notes_element && window.isWebReport) {	//hiddenTableNotes
		$("#print_note_" + table_data.table_id).html($(notes_element).html());
		$("#print_note_" + table_data.table_id).find("a").attr("name", "");
	}*/
}

function initNotesAndSources() {
	var notes = $("#" + table_notes)[0];
	var src = $('#table_source')[0];
	var html = ["", "", "", ""];
	if (notes && src) {
		table_id_list.forEach(function (v) {
			if ($(notes).html() === "") {
				html[0] += "<div id='" + v + "_table_notes_" + table_notes + "'></div>";
				html[1] += "<div id='" + v + "_table_header_notes_" + table_notes + "'></div>";
				html[2] += "<div id='" + v + "_table_sd_notes_" + table_notes + "'></div>";
			}
			if ($(src).html() === "") {
				html[3] += "<div id='" + v + "_table_source' class='sub_table_source table_src_notes_container'></div>";
			}
		});
		if (html[0]) {
			html[0] = "<div id='table_notes_" + table_notes + "' class='sub_table_notes table_src_notes_container'>" + html[0] + "</div>";
		}
		if (html[1]) {
			html[1] = "<div id='table_header_notes_" + table_notes + "' class='sub_table_notes table_src_notes_container'>" + html[1] + "</div>";
		}
		if (html[2]) {
			html[2] = "<div id='table_sd_notes_" + table_notes + "' class='sub_table_notes table_src_notes_container'>" + html[2] + "</div>";
		}
		$(notes).append(html[0] + html[1] + html[2]);
		$(src).append(html[3]);
	}
}

function removeNotesAndSourceItem(itm) {
	var container = $(itm).closest(".table_src_notes_container");
	if ($(itm).html() === "") {
		$(itm).remove();
	}
	if (container && $(container).html() === "") {
		$(container).remove();
	}	
}

function clearAllNotesAndSources() {
	$("#" + table_notes).html("");
	$('#table_source').html("");
	note_data_array = [];
	source_data_array = [];
	console.log("notes and sources cleared");
}

function generateNotesForMap(table_data) {
	initNotesAndSources();
	table_data.notes_data = [];
	table_data.source_data = [];
	var notes_tbl = $("#" + table_data.table_id + "_table_notes_" + table_notes)[0];
	var notes_hdr = $("#" + table_data.table_id + "_table_header_notes_" + table_notes)[0];
	var notes_sd = $("#" + table_data.table_id + "_table_sd_notes_" + table_notes)[0];
	var src = $("#" + table_data.table_id + "_table_source")[0];
	if (notes_tbl) {
		if (table_data.lang_data.tb_fn) {
			var skip = getNotesItem(table_data, table_data.lang_data.tb_fn, 'table');
			row_counter = generateNotesRow(notes_tbl, 0, table_data.lang_data.tb_fn, table_data.notes_data, skip);
			note_data_array.push({
				subjects: getSubjectCodes(table_data),
				notes: table_data.lang_data.tb_fn,
				note_type: 'table',
				table_id: table_data.table_id
			});
		}
		removeNotesAndSourceItem(notes_tbl);
	}
	if (notes_hdr) {
		var cntr = 1;
		table_data.footnote_used_list.forEach(function (v) {
			var div_element = document.createElement("div");
			div_element.classList.add('note_row');
			div_element.classList.add('footnote_lnks');			
			notes_hdr.appendChild(div_element);
			var div_element_1 = document.createElement("div");
			div_element_1.classList.add('sd_td');
			var id = table_data.table_id + '_' + cntr;
			var table_order_footnote_index_id = 'cdm_footnote_text_' + table_order_footnote_index_id_counter;				
			var table_order_footnote_index_obj;
			if (table_order_footnote_index_map[id]) {
				table_order_footnote_index_obj = table_order_footnote_index_map[id];
			} else {
				table_order_footnote_index_obj = {
					table_order_footnote_index_id: [],
					table_order_footnote_index_number: null,
					table_order_footnote_index_text: null
				};
				table_order_footnote_index_map[id] = table_order_footnote_index_obj;
			}
			table_order_footnote_index_map[id].table_order_footnote_index_text = table_order_footnote_index_id;
			table_order_footnote_index_id_counter++;				
			div_element_1.innerHTML = '<a name="' + table_data.table_id + '_' + cntr + '" style="text-decoration: none;">' + cntr + '</a>';
			div_element.appendChild(div_element_1);			
			var div_element_2 = document.createElement("div");
			div_element_2.classList.add('note_row_detail');
			div_element_2.innerHTML = v;
			div_element.appendChild(div_element_2);			
			var note_row = [cntr, v];
			table_data.notes_data.push(note_row);
			cntr += 1;
		});
		removeNotesAndSourceItem(notes_hdr);
	}
	if (notes_sd) {
		table_data.sd_used_list.forEach(function (v) {
			if (v != 0) {
				var sd = table_data.sd_list[v];
				var sd_desc = sd.sd_desc;
				var sd_sybmol = sd.sd_symbol;
				var noteItem = getNotesItem(table_data, sd_sybmol, 'sd_value');
				if (!noteItem) {
					var div_element = document.createElement("div");
					div_element.classList.add('note_row');
					div_element.classList.add("footnote_lnks");
					notes_sd.appendChild(div_element);
					var div_element_1 = document.createElement("div");
					div_element_1.classList.add('sd_td');				
					//div_element_1.innerHTML = '<a name="' + table_data.table_id + '_' + sd_sybmol + '" style="text-decoration: none;">' + sd_sybmol + '</a>';
					div_element_1.innerHTML = '<a name="' + sd_sybmol + '" style="text-decoration: none;">' + sd_sybmol + '</a>';
					div_element.appendChild(div_element_1);				
					var div_element_2 = document.createElement("div");
					div_element_2.classList.add('note_row_detail');
					div_element_2.innerHTML = sd_desc;
					div_element.appendChild(div_element_2);
					var note_row = [sd_sybmol, sd_desc, 'SD_VALUE'];
					table_data.notes_data.push(note_row);				
					note_data_array.push({
						subjects: getSubjectCodes(table_data),
						notes: sd_sybmol,
						note_type: 'sd_value',
						table_id: table_data.table_id
					});
				} else if (noteItem.table_id !== table_data.table_id) {
					var note_row = [sd_sybmol, sd_desc, 'SD_VALUE'];
					table_data.notes_data.push(note_row);				
					note_data_array.push({
						subjects: getSubjectCodes(table_data),
						notes: sd_sybmol,
						note_type: 'sd_value',
						table_id: table_data.table_id
					});
				}
			}
		});
		removeNotesAndSourceItem(notes_sd);
	}
	table_data.notes_data_export = clone(table_data.notes_data);
	if (src) {
		table_data.source_data.push([]);
		var note_item = getSourceItem(table_data);
		generateNotesRow(src, 0, table_data.lang_data.tb_src, table_data.source_data, note_item && note_item.id !== table_data.table_id);
		if (!note_item && table_data.lang_data.tb_src) {
			source_data_array.push({
				subjects: getSubjectCodes(table_data),
				notes: table_data.lang_data.tb_src,
				id: table_data.table_id
			});
		}
		removeNotesAndSourceItem(src);
	}
}

function addNoteText(note_array, record) {
	for (var i = 1; i <= 10; i++) {
		var text = record['note' + i];
		note_array.push(removeHtmlCode(text));
	}
	return note_array;
}

function generateDefault(type, no_sd_value){
	var table_id = table_id_list[0];
	generateDownload(type, table_id_list, no_sd_value);
}

/*$(window).bind('touchmove', function (e) {
	e.preventDefault();
});*/