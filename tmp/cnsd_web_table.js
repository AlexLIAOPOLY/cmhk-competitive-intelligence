var time_category_value_map = [];
var time_category_value_year_only = false;
var chart_without_table_all_load = false;
var en_url = '';
var tc_url = '';
var checkbox_id_list = [];
var checkbox_id_map = [];
var sv_sp_checkbox_id_list = [];
var LATEST = 'l';
var IS_REVERSE = 'tvrvs'
var bookmark_url = '';
var RADIO = 'radio';
var pac_hide_total = [];
var tooltipsLoaded = false;
//added 20230620
var minOptionsToShowSlider = 2;
var sliderOptionBag = {CCYY:[],CCYY_F:[]};

//end added 20230620
var webtable_textArr = {
	 'en': {
      'discrete_view': 'Specific Years',
	  'range_view':'Year Range',
      'from' : 'From',
	  'to' : 'To',
	  
    },
    'tc': {
      'discrete_view': '個別年份',
      'range_view' : '年份範圍',
	  'from' : '從',
	  'to' : '到',
    },
    'sc': {
      'discrete_view': '个别年份',
      'range_view':'年份范围',
	  'from' : '从',
	  'to' : '到',
    }
	
};

var url_path = location.pathname;
var url_lang = url_path.substring(1, 3).toLowerCase();

if (!window.isWebReport) {
	if (parameter_index >= 0) {
		var parameters = href.substring(parameter_index + 1);
		var hash_index = parameters.indexOf('#');
		if (hash_index >= 0) {	// remove those string after #
			parameters = parameters.substring(0, hash_index);
		}
		var url_vars = getUrlVarsParam(parameters);
		if (url_vars['id']) {
			table_id_list = [];
			table_id_list.push(url_vars['id']);
		} else if (typeof url_vars['id'] !== 'undefined') {
			getTableListPage();
		}
		if (url_vars['api_popup'] && url_vars['api_popup'] == 1) {
			api_popup = true;
		}
		if (url_vars['download_excel'] && url_vars['download_excel'] == 1) {
			download_excel = true;
			close_download = true;
		}
		if (url_vars['download_excel_excl'] && url_vars['download_excel_excl'] == 1) {
			download_excel_excl = true;
			close_download = true;
		}
		if (url_vars['download_csv'] && (url_vars['download_csv'] == 1)) {
			download_csv = true;
			close_download = true;
		}
		if (url_vars['download_csv_excl'] && url_vars['download_csv_excl'] == 1) {
			download_csv_excl = true;
			close_download = true;
		}
		if (url_vars['download_csv_tabular'] && url_vars['download_csv_tabular'] == 1) {
			download_csv_tabular = true;
			close_download = true;
		}
		if (url_vars['download_xml'] && url_vars['download_xml'] == 1) {
			download_xml = true;
			close_download = true;
		}
		if (url_vars['download_sdmx'] && url_vars['download_sdmx'] == 1) {
			download_sdmx = true;
			close_download = true;
		}
		if (url_vars['full_series'] && url_vars['full_series'] == 1) {
			full_series = true;
		}
	}
}

function handleTotalShowHide(flag) {
	/*if (flag) {
		$(".total_checkbox").closest(".cdm_checkbox").show();
		pac_hide_total.forEach(function (v) {
			var id = CV + "_total_" + v;
			var check = $("#" + id)[0];
			if (check && check.classList.contains("pac_total")) {
				$(check).closest(".cdm_checkbox").hide();
			}
		});
	} else {
		$(".total_checkbox").closest(".cdm_checkbox").hide();
	}*/
}

function initCloseBtn() {
	$(".ui-dialog-titlebar-close").attr("title", menu_text.close);
	$(".ui-dialog-titlebar-close").html('<i class="fas fa-times closeIcon"></i>');
}

function webTableInit() {
	$(".icon_full_series").bind("click",function() {
		selectAll(true, true);
		displaySelectedData();
		$("#default_series_button").show();
		$("#full_series_button").hide();
	});
	$(".icon_default_series").bind("click",function() {
		resetDefaultData();
		displaySelectedData();
		$("#default_series_button").hide();
		$("#full_series_button").show();
	});
	$(".icon_bookmark").bind("click",function() {
		showBookmarkPopup();
	});
	$(".icon_api").bind("click",function() {
		showApiPopup();
	});
	$(".icon_chart").bind("click",function() {
		$(".icon_table").show();
		$(".table_show").hide();
		$(".icon_chart").hide();
		$(".chart_show").show();
		$(".footnote_lnks").hide();
		$(".chart_footnote_lnks").show();
		handleTotalShowHide(false);
		redrawCharts(true);
		setChartHiddenChartCvCcDisplayStyle('none');
		setChartHiddenChartCvDisplayStyle('none');
		setChartHiddenChartSvSpDisplayStyle('none', true);
		$(".positions").hide();
		$(".cv_all_checkbox").toArray().forEach(function (v) {
			var class_var = v.id.replace(CV_ALL + "_", "");
			reviseCheckAllCheckBoxStatus(true, class_var);
		});
	});
	$(".icon_table").bind("click",function() {
		$(".icon_table").hide();
		$(".table_show").show();
		$(".icon_chart").show();
		$(".chart_show").hide();
		$(".footnote_lnks").show();
		handleTotalShowHide(true);
		setChartHiddenChartCvCcDisplayStyle('flex');
		setChartHiddenChartCvDisplayStyle('block');
		setChartHiddenChartSvSpDisplayStyle('flex', false);
		$(".positions").show();
		$(".cv_all_checkbox").toArray().forEach(function (v) {
			var class_var = v.id.replace(CV_ALL + "_", "");
			reviseCheckAllCheckBoxStatus(true, class_var);
		});
	});
	$(".icon_cust").bind("click",function() {
		openCust();
	});
	
	var dataDir = "/data/";
	if ((typeof(idds) != 'undefined') && (idds)) {
		// do nothing here
	} else if ((typeof cdm_text_file === 'undefined') || (typeof table_id_list !== 'undefined')) {
		if (typeof table_id_list !== 'undefined') {
			if (table_id_list.length === 0 && !window.isWebReport) {
				getTableListPage();
			}
			var table_id_promise = new Promise((resolve, reject) => {
				$.ajax({
					url: getCacheFile('/data/ops_mapping_table.csv'),
					async: true,
					success: function (data) {
						if (data) {
							var tables = $.csv.toObjects(data);
							var temp = clone(table_id_list);
							table_id_list = [];
							temp.forEach(function (v) { 
								var tableSetting = tables.filter(function (f) {
									return f.old.toLowerCase() === v.toLowerCase();
								})[0];
								if (tableSetting) {
									table_id_list.push(tableSetting.new);
								} else {
									table_id_list.push(v);
								}
							});
						}
					},
					dataType: "text",
					complete: function () {
						resolve(table_id_list);
					}
				});
			});
			table_id_promise.then((result) => {
				if (result && result.length > 0) {
					buildMultipleTables("table", result);
				} else {
					getTableListPage();
				}
			});
		} else {
			return;
		}
	} else if (typeof cdm_text_file !== 'undefined' && cdm_text_file) {
		loadCdmTextFile(dataDir);
		return;
	}
	if (table_id_list.length > 1) {
		$(".table_show").hide();
	} else {
		$(".chart_show").hide();
	}
}

function openCust() {
	for (i = 0; i < table_id_list.length; i++) {
		var table_id = table_id_list[i];
		var table_data = jQuery.extend(true, { }, table_data_list[table_id]);
		setCvCheckBoxFromTableData(table_data);
		setSvSpCheckBoxFromTableData(table_data);
	}
	var dialog_data = document.getElementById('cust_menu');
	dialog_data.title = menu_text.cust;
	$("#cust_menu").dialog({
		minWidth: 800,
		position: { my: "right top", at: "right top", of: window },
		resizable: false
	});
	$("#cust_menu").parent().css("position", "fixed");
	$("#cust_menu").parent().css("top", "0");
	$("#cust_panel").css("height", (window.innerHeight - 120 - $("#cust_control").height()) + "px", "important");
	initCloseBtn();
}

function setCvCheckBoxFromTableData(table_data, ignore_display) {
	if ($("#cust_menu")[0]) {
		if (table_data.component_data.rev_chrono) {
			$("#rdoTVSortingDesc")[0].checked = true;
		} else {
			$("#rdoTVSortingAsc")[0].checked = true;
		}
	}
	var checkbox_element = document.getElementById('classificationCheckBoxes');
	if (checkbox_element) {
		var skip_time_series = false;	
		var tvCheckedValues = [];
		// checkbox
		for (var class_var in table_data.lang_data.cv_list) {			
			var cv_record = table_data.lang_data.cv_list[class_var];			
			var comp_cv_record = table_data.component_data.table_component_ccg_list[class_var];
			var cv_index = table_data.cv_index_map[class_var];			
			// special handling for time series cv radio button
			if (cv_record.is_time_series == 1) {
				cv_index = TS_INDEX;
				//table_data.tv_range
				//tvCheckedValues
			}
			var radio_1_id = getCvRadioButtonValueName(CV + '_' + cv_index, ROW);
			var radio_2_id = getCvRadioButtonValueName(CV + '_' + cv_index, COLUMN);			
			var cv_radio_1 = document.getElementById(radio_1_id);
			var cv_radio_2 = document.getElementById(radio_2_id);			
			if (comp_cv_record.cv_position == ROW) {
				cv_radio_1.checked = true;
			} else if (comp_cv_record.cv_position == COLUMN) {
				cv_radio_2.checked = true;
			}
			// no checkbox for time series if it has No CCYY TV
			if (cv_record.is_time_series && skip_time_series) {
				continue;
			}			
			var temp_ccg_list = cv_record.ccg_list;
			var all_show = true;
			// update cc checkbox
			for (var ccg_index in temp_ccg_list) {
				var temp_ccg_record = temp_ccg_list[ccg_index];
				var temp_cc_list = temp_ccg_record.cc_list;
				var cc_cntr = 0;
				for (var class_code in temp_cc_list) {
					var cc_record = temp_cc_list[class_code];
					if (cc_record.has_data && cc_record.cc_index) {					
						var cc_index = cc_record.cc_index;
						var checkbox_id = CC + "_" + cc_index;
						var checkbox = document.getElementById(checkbox_id);
						if (checkbox) {
							checkbox.checked = cc_record.show;
							if ([CCYY, CCYY_F].includes(class_var) && cc_record.show) {
								tvCheckedValues.push(cc_cntr);
							}
							if (ignore_display || $(checkbox).closest(".cdm_checkbox")[0].style.display !== "none") {
								all_show = all_show && cc_record.show;
							}
						}
					}
					cc_cntr++;
				}
			}			
			if ([CCYY, CCYY_F].includes(class_var) && tvCheckedValues?.length > 0) {
				tvCheckedValues = tvCheckedValues.sort((a, b) => { return a < b ? -1 : 1; });
				redrawSlider(class_var, [tvCheckedValues[0], tvCheckedValues.slice(-1)[0]]);
				createsliderOptionBag(class_var);
			}
			// update total checkbox
			//var first_ccg = getFirstCCGForTotal(table_data, class_var);
			//var show_flg = table_data.component_data.table_component_ccg_list[class_var].ccg_list.filter(function (v) { return v.cv_total_show > 0 && v.class_code_group === first_ccg; }).length > 0;
			var show_flg = table_data.component_data.table_component_ccg_list[class_var].ccg_list.filter(function (v) { return v.cv_total_show > 0; }).length > 0;
			var total_checkbox = $("#" +  CV + "_total_" + class_var)[0];
			if (total_checkbox && (ignore_display || $(total_checkbox).closest(".cdm_checkbox")[0].style.display !== "none")) {
				total_checkbox.checked = show_flg;
				all_show = all_show && show_flg;
			}
			reviseCheckAllCheckBoxStatus(all_show, class_var);
		}		
	}	
}
function getFirstCCGForTotal(table_data, class_var) {
	var first_ccg = null;
	for (var temp_ccg in table_data.lang_data.cv_list[class_var].ccg_list) {
		first_ccg = temp_ccg;
		break;
	}
	return first_ccg;
}
function setSvSpCheckBoxFromTableData(table_data) {
	var check_boxes_element = document.getElementById('statisticsCheckBoxes');
	if (check_boxes_element) {
		// radio buttons for position
		var radio_1_id = getSvRadioButtonValueName(SV, ROW_LEFT);
		var radio_2_id = getSvRadioButtonValueName(SV, ROW_RIGHT);
		var radio_3_id = getSvRadioButtonValueName(SV, COLUMN_TOP);
		var radio_4_id = getSvRadioButtonValueName(SV, COLUMN_BOTTOM);
		var sv_radio_1 = document.getElementById(radio_1_id);
		var sv_radio_2 = document.getElementById(radio_2_id);
		var sv_radio_3 = document.getElementById(radio_3_id);
		var sv_radio_4 = document.getElementById(radio_4_id);		
		if (table_data.component_data.sv_position == ROW_LEFT) {
			sv_radio_1.checked = true;
		} else if (table_data.component_data.sv_position == ROW_RIGHT) {
			sv_radio_2.checked = true;
		} else if (table_data.component_data.sv_position == COLUMN_TOP) {
			sv_radio_3.checked = true;
		} else if (table_data.component_data.sv_position == COLUMN_BOTTOM) {
			sv_radio_4.checked = true;
		}
		for (var stat_var in table_data.lang_data.sv_list) {
			var sv_record = table_data.lang_data.sv_list[stat_var];
			var sv_index = sv_record.sv_index;
			// sp fields
			for (var stat_pres in sv_record.sp_list) {
				var sp_record = sv_record.sp_list[stat_pres];
				var sp_index = sp_record.sp_index;
				var sv_sp_index = sv_index + '_' + sp_index;
				var sp_checkbox_id = SP + '_' + sv_sp_index;
				var sp_checkbox = document.getElementById(sp_checkbox_id);				
				sp_checkbox.checked = sp_record.show;				
			}
		}
	}
}

function reviseCheckAllCheckBoxStatus(new_status, class_var) {
	var all_checkbox_id = CV_ALL + "_" + class_var;
	var local_all_checkbox_element = document.getElementById(all_checkbox_id);
	if (local_all_checkbox_element) {
		// if uncheck, then ALL need to be unchecked
		if (!new_status) {
			local_all_checkbox_element.checked = false;
		} else {
			// if check, see if it needs to update ALL check status
			var current_checkbox_id_list = checkbox_id_map[class_var];
			var i;
			var all_check = true;
			for (i = 0; i < current_checkbox_id_list.length; i++) {
				var checkbox = document.getElementById(current_checkbox_id_list[i]);
				var div = $(checkbox).closest(".cdm_checkbox")[0];
				if (div && div.style.display !== "none") {
					all_check = all_check && checkbox.checked;
				}
			}
			if (all_check) {
				local_all_checkbox_element.checked = true;
			} else if (local_all_checkbox_element.checked) {
				local_all_checkbox_element.checked = false;
			}
		}
	}
}

function setHTMLforLabel(txt, inline) {
	return "<div " + (inline ? "style='display: inline-flex'" : "") + ">" + txt + "</div>";//removeHtmlCode(txt);
}

function setHTMLforLabel2(txt) {
	return "<span>" + txt + "</span>";
}

function buildSvSpCheckBox(table_data) {
	var check_boxes_element = document.getElementById('statisticsCheckBoxes');
	if (check_boxes_element) {		
		sv_sp_checkbox_id_list = [];
		var sv_div = document.createElement('div');
		sv_div.classList.add('statistic_result_3');
		check_boxes_element.appendChild(sv_div);		
		var subject_right_sub_title_div = document.createElement('div');
		subject_right_sub_title_div.classList.add('subject_right_sub_title');
		subject_right_sub_title_div.classList.add('margin_top_30');
		sv_div.appendChild(subject_right_sub_title_div);		
		var title_h = document.createElement('div');
		title_h.classList.add('h6');
		title_h.innerHTML = setHTMLforLabel(cust_text.sv, true);
		title_h.setAttribute("data-bs-target", "#sv_cust");
		title_h.setAttribute("data-bs-toggle", "collapse");
		title_h.innerHTML = title_h.innerHTML + '<i aria-hidden="true" class="material-icons" ><span class="dummy_collapse">' + title_h.innerHTML + ' ' + cust_text.exp_col + '</span></i>';
		var title_a = document.createElement('a');
		title_a.classList.add('expand_more_less');
		title_a.innerHTML = title_h.outerHTML;
		title_a.href = "#sv_cust";
		title_a.setAttribute("data-bs-toggle", "collapse");
		title_a.setAttribute("aria-expanded", "true");
		subject_right_sub_title_div.appendChild(title_a);		
		var detail_div = document.createElement('div');
		detail_div.classList.add('collapse');
		detail_div.classList.add('show');
		detail_div.id = 'sv_cust';
		sv_div.appendChild(detail_div);		
		var sv_body_div = document.createElement('div');
		sv_body_div.classList.add('sv_body');
		sv_body_div.classList.add('positions');
		detail_div.appendChild(sv_body_div);	
		var p_h1 = document.createElement("span");
		p_h1.innerHTML = table_text.position;
		sv_body_div.appendChild(p_h1);	
		// radio buttons for position
		var radio_1 = buildSvRadioButton(SV, ROW_LEFT);
		var radio_2 = buildSvRadioButton(SV, ROW_RIGHT);
		var radio_3 = buildSvRadioButton(SV, COLUMN_TOP);
		var radio_4 = buildSvRadioButton(SV, COLUMN_BOTTOM);		
		var p_1 = document.createElement("label");
		var p_2 = document.createElement("label");
		var p_3 = document.createElement("label");
		var p_4 = document.createElement("label");
		p_1.setAttribute('for', radio_1.id);
		p_2.setAttribute('for', radio_2.id);
		p_3.setAttribute('for', radio_3.id);
		p_4.setAttribute('for', radio_4.id);
		p_1.classList.add('for_checkbox');
		p_2.classList.add('for_checkbox');
		p_3.classList.add('for_checkbox');
		p_4.classList.add('for_checkbox');		
		p_1.innerHTML = table_text.row.trim() + table_text.head;
		p_2.innerHTML = table_text.row.trim() + table_text.sub_head;
		p_3.innerHTML = table_text.column.trim() + table_text.head;
		p_4.innerHTML = table_text.column.trim() + table_text.sub_head;
		var br_0 = document.createElement("br");		
		var sv_sub_body_div_1 = document.createElement('div');
		sv_sub_body_div_1.classList.add('sv_sub_body');
		sv_body_div.appendChild(sv_sub_body_div_1);
		var sv_sub_body_div_2 = document.createElement('div');
		sv_sub_body_div_2.classList.add('sv_sub_body');
		sv_body_div.appendChild(sv_sub_body_div_2);
		sv_sub_body_div_1.appendChild(radio_1);
		sv_sub_body_div_1.appendChild(p_1);
		sv_sub_body_div_1.appendChild(radio_2);
		sv_sub_body_div_1.appendChild(p_2);
		sv_sub_body_div_2.appendChild(radio_3);
		sv_sub_body_div_2.appendChild(p_3);
		sv_sub_body_div_2.appendChild(radio_4);
		sv_sub_body_div_2.appendChild(p_4);
		
		table_data.component_data.table_component_list.sort(function (a, b) { 
			var aseq = a.display_order ? parseInt(a.display_order) : -1;
			var bseq = b.display_order ? parseInt(b.display_order) : -1;
			return aseq < bseq ? -1 : 1;
		}).forEach(function (svsp) {
			var sv_record = table_data.lang_data.sv_list[svsp.stat_var];
			var sv_index = sv_record.sv_index;			
			var sp_record = sv_record.sp_list[svsp.stat_pres];
			var sp_index = sp_record.sp_index;
			var sv_sp_index = sv_index + '_' + sp_index;				
			var chart_matched_sv_sp = false;
			for (var check_chart_code in table_data.chart_data) {
				var chart_obj = table_data.chart_data[check_chart_code];
				if (chart_obj.y_axis.setting.filter(function (v) { return v.stat_var === svsp.stat_var && v.stat_pres === svsp.stat_pres}).length > 0) {
					chart_matched_sv_sp = true;
					break;
				}
			}				
			var checkbox_div_element = document.createElement("div");
			checkbox_div_element.classList.add(CDM_CHECKBOX_CLASS_NAME);
			if (!chart_matched_sv_sp) {
				checkbox_div_element.classList.add(HIDDEN_CHART_SV_SP_CLASS_NAME);
			}				
			var sp_checkbox = document.createElement("input");   
			sp_checkbox.value = sv_sp_index;
			sp_checkbox.type="checkbox";
			var sp_checkbox_id = SP + '_' + sv_sp_index;
			sp_checkbox.id = sp_checkbox_id;
			checkbox_id_list.push(sp_checkbox_id);
			sv_sp_checkbox_id_list.push(sp_checkbox_id);
			var sp_p = document.createElement("label");
			sp_p.innerHTML = setHTMLforLabel(' ' + sv_record.def_stat_desc + ' - ' + sp_record.def_stat_pres_desc);
			sp_p.setAttribute('for', sp_checkbox_id);
			sp_p.classList.add('for_checkbox');
			var sp_br = document.createElement("br");				
			sp_checkbox.checked	= true;
			var div = document.createElement("div");
			$(div).append(sp_checkbox);
			checkbox_div_element.appendChild(div);
			checkbox_div_element.appendChild(sp_p);
			checkbox_div_element.appendChild(sp_br);
			detail_div.appendChild(checkbox_div_element);
		});					
	}
}

// action performed when user press the submit button, which the table will display the result.
function displaySelectedData(refreshMenu) {
	
	//added 20230620
	var myElem = document.getElementsByClassName('discrete_range');	
	if (myElem !== null)
	{
		
		var val = $("#radio_discrete_" + CCYY).prop("checked");
		if (val == true)
		{	
			$('#radio_range_CCYY').click();
			overrideSliderValues(CCYY);		
		}	
		else
		{
			overrideCheckboxValues(CCYY);	
			createsliderOptionBag(CCYY);
		}
		var val = $("#radio_discrete_" + CCYY_F).prop("checked");
		
		if (val==true)
		{
			$('#radio_range_CCYY_F').click();
			overrideSliderValues(CCYY_F);
			
		}
		else
		{
			overrideCheckboxValues(CCYY_F);	
			createsliderOptionBag(CCYY_F);
		}
		
		
	}
	//end 
	
	var table_id = '';
	for (var i = 0; i < table_id_list.length; i++) {
		table_id = table_id_list[i];
		if (table_data_list[table_id].chart_data) {	//used for multiple y-axis
			for (var chart in table_data_list[table_id].chart_data) {
				table_data_list[table_id].chart_data[chart].reload_chart = true;
			}
		}
		var table_data = jQuery.extend(true, { }, table_data_list[table_id]);
		table_data.component_data.rev_chrono = $("#rdoTVSortingAsc:checked").length > 0 ? false : true;
		table_data.has_row = false;
		table_data.has_column = false;
		table_data.pac_error = [];		
		var cv_success = setCvShowFromCheckBox(table_data);
		if (!cv_success) {
			return;
		}
		var sv_sp_show_count = setSvSpShowFromCheckBox(table_data);
		if  (sv_sp_show_count == 0) {
			alert(error_msg.sv_options);
			return;
		}
		if (table_data.has_row && table_data.has_column) {
			//make build table before all the other options
			if (!window.isWebReport) {
				addLoadingPanel();
			}
			sleepTime(0).then(function () {				
				$.when(				
					buildCdmTable(table_data)
				).then(function() { 
					//fixed re-generate table and tooltip not synchronized 20211220
					generateCurrentSelectionUrl(table_data);
					generateCurrentSelectionJson(table_data);
					if (!window.isWebReport) {
						hideLoading(null, 't');
						//hideLoadingById("t", table_data.table_id);
					}
					table_data_list[table_id].ccyy_time_series_list = table_data.ccyy_time_series_list;
					table_data_list[table_id].lang_data = table_data.lang_data;
					table_data_list[table_id].component_data = table_data.component_data;
					table_data_list[table_id].notes_data = table_data.notes_data;
					table_data_list[table_id].sd_used_list = table_data.sd_used_list;
					table_data_list[table_id].source_data = table_data.source_data;
					buildTableCharts(table_data);
				});	
				if (table_data.pac_error && table_data.pac_error.length > 0) {
					alert(table_data.pac_error.join("\n"));
				}					
			});
		} else {
			alert(error_msg.cv_options);
			return;
		}
	}
	// for access log
	if (!escapeAccessLog) {
		$.ajax({
			url: '/web_table_cust.txt?table_id=' + table_id,
			async: true,
			success: function (data) {
			},
			dataType: "text",
			complete: function () {
			}
		});
	}
	escapeAccessLog = false;
	if (!refreshMenu) {
		closeCust();
	}
	if (!window.isWebReport) {
		pivotTableDivScrolling($(".pivotTableContainer")[0]);
		checkAllInputs(table_data);
	}
	
}

function checkAllInputs(table_data) {
	var result = "";
	var all_flag = true;
	var default_flag = false;
	var radios = "";
	$("#cust_menu input[type='checkbox']").toArray().reverse().forEach(function (v) {
		var val = $(v).prop("checked");
		result += (val ? "1" : "0");
		if (!val) {
			all_flag = false;
		}
	});
	$("#cust_menu input[type='radio']").toArray().reverse().forEach(function (v) {
		var val = $(v).prop("checked");
		radios += (val ? "1" : "0");
	});
	if (!table_data.default_check) {
		table_data.default_check = {
			checks: result,
			radios: radios
		}
		default_flag = true;
	} else {
		if (table_data.default_check.checks === result && table_data.default_check.radios === radios) {
			default_flag = true;
		}
	}
	/*if (default_flag) {
		$("#default_series_button").hide();
	} else {
		$("#default_series_button").show();
	}
	if (all_flag) {
		$("#full_series_button").hide();
	} else {
		$("#full_series_button").show();
	}*/
}

function closeCust() {
	if (window.isWebReport) {
		return;
	}
	if ($("#cust_menu").hasClass("ui-dialog-content") &&
		$("#cust_menu").dialog("isOpen")) {
		$( "#cust_menu" ).dialog( "close" );
	}
}

function setCvShowFromCheckBox(table_data) {
	var checkbox_element = document.getElementById('classificationCheckBoxes');
	if (checkbox_element) {	
		// radio button
		for (var class_var in table_data.component_data.table_component_ccg_list) {
			var comp_cv_record = table_data.component_data.table_component_ccg_list[class_var];
			var cv_index = table_data.cv_index_map[class_var];			
			var cv_record = table_data.cv_map[cv_index];			
			// special handling for time series cv radio button
			if (cv_record.is_time_series == 1) {
				cv_index = TS_INDEX;
			}			
			var radio_1_id = getCvRadioButtonValueName(CV + '_' + cv_index, ROW);
			var radio_2_id = getCvRadioButtonValueName(CV + '_' + cv_index, COLUMN);			
			var cv_radio_1 = document.getElementById(radio_1_id);
			var cv_radio_2 = document.getElementById(radio_2_id);			
			if (cv_radio_1.checked) {
				comp_cv_record.cv_position = ROW;
				table_data.has_row = true;
			} else if (cv_radio_2.checked) {
				table_data.has_column = true;
				comp_cv_record.cv_position = COLUMN;
			}
		}
		var skip_time_series = false;
		// checkbox
		var ccyy_show_list = [];
		var no_ccyy_tv_show_list = [];
		var tv_selected = false;
		var ccyy_desc = "";
		var ccyy_must_select = false;
		for (var class_var in table_data.lang_data.cv_list) {			
			var cv_record = table_data.lang_data.cv_list[class_var];			
			// no checkbox for time series if it has No CCYY TV
			if (cv_record.is_time_series === '1' && skip_time_series) {
				continue;
			}			
			var temp_ccg_list = cv_record.ccg_list;
			var cc_count = 0;			
			for (var ccg_index in temp_ccg_list) {
				var temp_ccg_record = temp_ccg_list[ccg_index];
				var temp_cc_list = temp_ccg_record.cc_list;				
				for (var class_code in temp_cc_list) {
					var cc_record = temp_cc_list[class_code];
					if (cc_record.not_pac) {
						continue;
					}
					if (cc_record.has_data && cc_record.cc_index) {
						var cc_index = cc_record.cc_index;
						var checkbox_id = CC + "_" + cc_index;
						var checkbox = document.getElementById(checkbox_id);
						cc_record.show = checkbox.checked;
						if (cc_record.show) {
							var div = $(checkbox).closest(".cdm_checkbox")[0];
							if (div && div.style.display !== "none") {
								cc_count++;
							}
						}						
						// also update the time series list show value
						if (cv_record.is_time_series) {
							if (no_ccyy_tv.includes(class_var)) {
								var itm = no_ccyy_tv_show_list.filter(function (v) { return v.class_var === class_var; })[0];
								if (itm) {
									itm.list[class_code] = checkbox.checked;
								} else {
									itm = { class_var: class_var, list: [] };
									itm.list[class_code] = checkbox.checked;
									no_ccyy_tv_show_list.push(itm);
								}
							} else if (class_var == CCYY) {								
								ccyy_show_list[class_code] = checkbox.checked;								
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
				}	
				var total_checkbox_id = CV + "_total_" + class_var;
				var total_checkbox = document.getElementById(total_checkbox_id);
				if (total_checkbox) {
					var cv_total_show = total_checkbox.checked;
					if ($(total_checkbox).closest(".cdm_checkbox")[0].style.display !== "none" && total_checkbox.checked) {
						cc_count++;
					}
					/*var first_ccg = getFirstCCGForTotal(table_data, class_var);
					var lst = table_data.component_data.table_component_ccg_list[class_var].ccg_list;
					for (var ccg_j in lst) {
						if (lst[ccg_j].class_code_group === first_ccg) {
							lst[ccg_j].cv_total_show = cv_total_show ? parseInt(lst[ccg_j].show_total) : 0;
						}
					}*/
					var lst = table_data.component_data.table_component_ccg_list[class_var].ccg_list;
					for (var ccg_j in lst) {
						lst[ccg_j].cv_total_show = cv_total_show ? parseInt(lst[ccg_j].show_total) : 0;
					}						
				}				
			}
			if (cc_count == 0) {
				var check_flag = true;
				var menu_item = $("#cust_" + class_var)[0];
				if (menu_item) {
					check_flag = $(menu_item).is(":visible");
				}
				if (check_flag) {
					if (class_var !== CCYY && cv_record.is_time_series == '1' && table_data.single_ccyy_allow) {
						// no need to select if this cv is time series, and CCYY has data by itself
					} else {
						if (cv_record.is_time_series == '1') {
							if (class_var !== CCYY) {
								//error_msgs.push(error_msg.single_cv_options.replaceAll("[CV_RECORD]",  cv_record.def_class_desc));
							} else {
								ccyy_desc = cv_record.def_class_desc;
							}
						} else {
							alert(error_msg.single_cv_options.replaceAll("[CV_RECORD]",  cv_record.def_class_desc));
							return false;
						}					
					}
				}
			} else {
				if (cv_record.is_time_series === "1" && (class_var !== CCYY || cv_record.tv_display_seq !== 0)) {
					tv_selected = true;
					if (class_var !== CCYY_F) {
						ccyy_must_select = true;
					}
				}
			}
		}
		if (!tv_selected) {
			alert(error_msg.tv_options.replaceAll("[CV_RECORD]", table_data.lang_data.cv_list[CCYY].def_class_desc));
			return false;
		}
		if (ccyy_must_select && ccyy_desc !== "") {
			alert(error_msg.single_cv_options.replaceAll("[CV_RECORD]",  ccyy_desc));
			return false;
		}
		no_ccyy_tv.forEach(function (t) {
			var itm = table_data.ccyy_time_series_list[t];
			if (table_data.lang_data.cv_list[t] && itm && itm.length > 0) {
				for (var i in itm) {
					var ccyy_time_series_record = itm[i];
					var ccyy_show = ccyy_show_list[ccyy_time_series_record.ccyy_index];
					var show_flg = false;
					var tv = no_ccyy_tv_show_list.filter(function (v) { return v.class_var === t; })[0];
					if (tv) {
						show_flg = tv.list[ccyy_time_series_record.time_series_index];
					}
					table_data.ccyy_time_series_map[t][ccyy_time_series_record.ccyy_index][ccyy_time_series_record.time_series_index].show = ccyy_show && show_flg;
				}
			}
		});
	}	
	return true;
}

function openCust_sma() {
	document.getElementById("cust_menu").style.display = 'block';
	document.body.scrollTop = 0;
	document.documentElement.scrollTop = 0;
}

// action performed when user press the reset button, which the table will display the default result.
function resetDefaultData(){
	for (i = 0; i < table_id_list.length; i++) {
		var table_id = table_id_list[i];
		var table_data = jQuery.extend(true, { }, table_data_list[table_id]);		
		setTableDataFromUrlParameter(table_data, table_data.original_url_parameters_map);		
		// set the radio / checkbox buttons base on the component settings
		setUiComponent(table_data, true);		
		table_data_list[table_id].ccyy_time_series_list = table_data.ccyy_time_series_list;
		table_data_list[table_id].lang_data = table_data.lang_data;
		table_data_list[table_id].component_data = table_data.component_data;
		table_data_list[table_id].component_data.rev_chrono = table_data.component_data.rev_chrono;
		checkTvSortingRadio(table_data_list[table_id]);
	}
	//added 20230620
	var myElem = document.getElementsByClassName('discrete_range');
	if (myElem.length>0) {
		if (checkIsBookmark()) {
			toggleDiscrete_Range(1,CCYY);
			toggleDiscrete_Range(1,CCYY_F);	
			createsliderOptionBag(CCYY);
			createsliderOptionBag(CCYY_F);
		} else {
			toggleDiscrete_Range(2,CCYY);
			toggleDiscrete_Range(2,CCYY_F);	
			overrideSliderValues(CCYY);
			overrideSliderValues(CCYY_F);
		}
	}
}

function loadCdmTextFile(dataDir) {
	var sd_path = dataDir + langDir + 'sd_lang.json';
	$.getJSON(sd_path, function (data) {
		all_sd_list = data;
		all_sd_load = true;
		loadSdDataWithoutTable();
	});
	$.getJSON(dataDir + langDir + cdm_text_file, function (data) {
		cdm_text_data = data;
		var mdt_filename_list = {};
		var chart_filename_list = {};		
		var is_overview = false;
		var is_short = true;
		if (pathname.indexOf('scode') >= 0) {
			is_overview = true;
			is_short = false;
		}		
		var variable_mapping_list = data.variable_mapping;
		for (var variable_mapping_index in variable_mapping_list) {
			var variable_mapping_record = variable_mapping_list[variable_mapping_index];
			var theme_id = variable_mapping_record.theme_id;
			var stat_var = variable_mapping_record.stat_var;
			var stat_pres = variable_mapping_record.stat_pres;
			// get mdt filenames
			var mdt_filename = getMdtFilename(theme_id, stat_var, stat_pres, null, is_overview, is_short);
			if (!all_mdt_list[stat_var]) {
				all_mdt_list[stat_var] = [];
			}
			var filepath = getMDT(dataDir, mdt_filename);
			mdt_filename_list[filepath] = {
				stat_var : stat_var,
				stat_pres : stat_pres,
				theme: theme_id,
				url : filepath
			};
			all_mdt_load[filepath] = false;
			// get chart filenames
			for (var chart_index in variable_mapping_record.chart) {
				var chart_record = variable_mapping_record.chart[chart_index];
				if (chart_record.element_id) {
					var chart_element = document.getElementById(chart_record.element_id);
					// only load if the chart element exist
					if (chart_element) {
						var chart_filename = getChartfilename(dataDir, chart_record.chart_code);
						chart_filename_list[chart_filename] = {
							chart_code : chart_record.chart_code,
							url : chart_filename,
						};
						all_chart_load[chart_filename] = false;
					}
				}
			}
		}
		// load the mdt files
		for (var mdt_filename in mdt_filename_list) {
			var mdt_filename_record = mdt_filename_list[mdt_filename];
			$.ajax({
				stat_var: mdt_filename_record.stat_var,
				stat_pres: mdt_filename_record.stat_pres,
				theme: mdt_filename_record.theme,
				url: mdt_filename,
				cdm_text_data: cdm_text_data,
				async: true,
				success: function (csvd) {
					//table_data.mdt_data[this.url] = $.csv.toObjects(csvd);
					// var csv_object = $.csv.toObjects(csvd);
					var parse_csv_object = Papa.parse(csvd, { header: true, skipEmptyLines: true });
					var csv_object = parse_csv_object.data;
					if (csv_object && csv_object.length > 0) {
						var theme = this.theme;
						csv_object.forEach(function (v) {
							v.mdt_theme_id = theme;
						});
					}
					if (!all_mdt_list[this.stat_var][this.stat_pres]) {
						all_mdt_list[this.stat_var][this.stat_pres] = csv_object;
					} else {
						all_mdt_list[this.stat_var][this.stat_pres] = all_mdt_list[this.stat_var][this.stat_pres].concat(csv_object);
					}
				},
				dataType: "text",
				error: function () {
					if (!all_mdt_list[this.stat_var][this.stat_pres]) {
						all_mdt_list[this.stat_var][this.stat_pres] = [];
					}
				},
				complete: function () {
					// call a function on complete 
					//table_data.dataPathLoaded = true;
					//loadJsonData(table_data);
					all_mdt_load[this.url] = true;
					loadMdtDataWithoutTable(cdm_text_data);
				}
			});
		}		
		// load chart files
		for (var chart_filename in chart_filename_list) {
			var chart_filename_record = chart_filename_list[chart_filename];
			$.ajax({
				chart_code: chart_filename_record.chart_code,
				url: chart_filename_record.url,
				async: true,
				success: function (chart_data_string) {
					all_chart_list[this.chart_code] = JSON.parse(chart_data_string);
				},
				dataType: "text",
				complete: function () {
					all_chart_load[this.url] = true;
					loadChartDataWithoutTable(cdm_text_data);
				}
			});
		}		
		loadMdtDataWithoutTable(cdm_text_data);
		loadChartDataWithoutTable(cdm_text_data);
		loadSdDataWithoutTable();
	});	
}

function setChartHiddenChartCvCcDisplayStyle(new_style) {
	setChartHiddenChartDisplayStyle(new_style, HIDDEN_CHART_CV_CC_CLASS_NAME);
	setChartHiddenChartDisplayStyle(new_style, HIDDEN_CHART_CV_CC_CLASS_NAME_BY_CHART_X_AXIS);
}

function setChartHiddenChartCvDisplayStyle(new_style) {
	setChartHiddenChartDisplayStyle(new_style, HIDDEN_CHART_CV_CLASS_NAME);
}

function setChartHiddenChartSvSpDisplayStyle(new_style, disable) {
	setChartHiddenChartDisplayStyle(new_style, HIDDEN_CHART_SV_SP_CLASS_NAME);
	for (var sv_sp_i in sv_sp_checkbox_id_list) {
		var sp_sp_id = sv_sp_checkbox_id_list[sv_sp_i];
		var check_boxes_element = document.getElementById(sp_sp_id);
		if (check_boxes_element) {
			check_boxes_element.disabled = disable;
		}
	}
}

function setChartHiddenChartDisplayStyle(new_style, hidden_chart_class_name) {
	$("." + hidden_chart_class_name).toArray().forEach(function(v) {
		v.style.display = new_style;
	});
}

function loadMdtDataWithoutTable(cdm_text_data) {
	for (var mtd_filename in all_mdt_load) {
		var loaded = all_mdt_load[mtd_filename];
		if (!loaded) {
			return;
		}
	}
	mdt_without_table_all_load = true;
	if (chart_without_table_all_load && all_sd_load) {
		setCdmText(cdm_text_data);
	}
}

function loadChartDataWithoutTable(cdm_text_data) {
	for (var chart_filename in all_chart_load) {
		var loaded = all_chart_load[chart_filename];
		if (!loaded) {
			return;
		}
	}
	chart_without_table_all_load = true;	
	if (mdt_without_table_all_load && all_sd_load) {
		setCdmText(cdm_text_data);
	}
}

function loadSdDataWithoutTable() {
	if (mdt_without_table_all_load && chart_without_table_all_load) {
		setCdmText(cdm_text_data);
	}
}

function processCdmTextMdt(variable_mapping_record, mdt) {
	var all_cvs = [];
	for (var cv in variable_mapping_record.cv_list) {
		if (variable_mapping_record.cv_list[cv].is_time_series !== "1") {
			all_cvs.push(cv);
		}
	}
	variable_mapping_record.mdt.forEach(function (m) {
		all_cvs.filter(function (f) { return !m.mdt_param.map(function (v) { return v.class_var; }).includes(f); }).forEach(function (v) {
			m.mdt_param.push({
				class_var: v,
				class_code: null
			});
		});
		m.mdt = mdt.slice(0);
		m.mdt_param.forEach(function (v) {
			m.mdt = m.mdt.filter(function (f) { 
				if (v.class_code) {
					return f[v.class_var] === v.class_code; 
				} else {
					return !f[v.class_var];
				}			
			});
		});
	});
}

function get_time_series_suffix(str){
	
 const suffixes = ['_H', '_M3M', '_MM', '_Q', '_YTM', '_YTQ'];
  str = str.toString();
  
  for (const suffix of suffixes) {
    if (str.endsWith(suffix)) {
      return suffix.slice(1); // Remove the underscore
    }
  }
  
  return '';
}

function setCdmText(cdm_text_data) {
	var variable_mapping_list = cdm_text_data.variable_mapping;
	var sd_used_list = [];
	var footnote_used_list = [];
	for (var variable_mapping_index in variable_mapping_list) {
		var variable_mapping_record = variable_mapping_list[variable_mapping_index];		
		var stat_var = variable_mapping_record.stat_var;
		var stat_pres = variable_mapping_record.stat_pres;
		var mdt = all_mdt_list[stat_var][stat_pres].filter(function (f) { return f.mdt_theme_id === variable_mapping_record.theme_id; });
		processCdmTextMdt(variable_mapping_record, mdt);
		// display sp text
		var current_sp_record = null;
		for (var sp_index in variable_mapping_record.sp_text) {
			var sp_record = variable_mapping_record.sp_text[sp_index];
			if (!all_sv_list[sp_record.stat_var]) {
				all_sv_list[sp_record.stat_var] = {
					sp_list : [],
				}
			}
			if (!all_sv_list[sp_record.stat_var].sp_list[sp_record.stat_pres]) {
				all_sv_list[sp_record.stat_var].sp_list[sp_record.stat_pres] = {
					def_stat_pres_desc : sp_record.def_stat_pres_desc,
					def_separator_format : sp_record.def_separator_format,
				}
			}
			
			if (sp_record.element_id) {
				var sp_element = document.getElementById(sp_record.element_id);
				if (sp_element) {
					var record_text = sp_record.def_stat_pres_desc;
					record_text = createFootnote(sp_record, record_text, footnote_used_list, null);
					sp_element.innerHTML = setHTMLforLabel2(record_text);//setHTMLforLabel(record_text, true);
				}
			}
			
			if ((sp_record.stat_var == stat_var) && (sp_record.stat_pres == stat_pres)) {
				current_sp_record = sp_record;
			}
		}		
		// display cv text
		var default_show_latest_record_number_map = {};
		for (var cv_index in variable_mapping_record.cv_text) {
			var cv_record = variable_mapping_record.cv_text[cv_index];
			if (cv_record.element_id) {
				var cv_element = document.getElementById(cv_record.element_id);
				if (cv_element) {
					var record_text = cv_record.def_class_desc;
					record_text = createFootnote(cv_record, record_text, footnote_used_list, null);
					cv_element.innerHTML = setHTMLforLabel2(record_text);	//setHTMLforLabel(record_text, true);
				}
			}			
			if (cv_record.default_show_latest_record_number) {
				default_show_latest_record_number_map[cv_record.class_var] = Number(cv_record.default_show_latest_record_number);
			}
		}
		var time_series_individual_map = {};
		var time_series_list = [];
		for (var current_class_var in variable_mapping_record.cv_list) {			
			time_series_individual_map[current_class_var] = [];
			var cv_record = variable_mapping_record.cv_list[current_class_var];
			var ccg_list = cv_record.ccg_list;
			for (var ccg_index in ccg_list) {
				var cc_list = ccg_list[ccg_index].cc_list;				
				for (var cc_index in cc_list) {
					var cc_record = cc_list[cc_index];
					/*if (mdt) {
						var temp_mdt = $.grep(mdt, function (obj) { return (obj[current_class_var] == cc_record.class_code); });
						if (temp_mdt.length > 0) {
							cc_record.show = true;
							if (cv_record.is_time_series == '1') {
								time_series_individual_map[current_class_var].push(cc_record);
							}
						}						
					}*/
					for (var i = 0; i < variable_mapping_record.mdt.length; i++) {
						if (variable_mapping_record.mdt[i].mdt) {
							var temp_mdt = $.grep(variable_mapping_record.mdt[i].mdt, function (obj) { return (obj[current_class_var] == cc_record.class_code); });
							if (temp_mdt.length > 0) {
								cc_record.show = true;
								if (cv_record.is_time_series == '1') {
									time_series_individual_map[current_class_var].push(cc_record);
								}
								break;
							}		
						}
					}
				}
			}			
			// set the default show latest record
			if (default_show_latest_record_number_map[current_class_var]) {
				var default_show_latest_record_number = default_show_latest_record_number_map[current_class_var];				
				var cc_list = time_series_individual_map[current_class_var];
				cc_list.sort(compareClassCodeSeq);				
				for (var z = 0; z < cc_list.length - default_show_latest_record_number; z++) {
					var cc_record = cc_list[z];
					cc_record.show = false;
				}
			}
		}
		
		//remove empty array from timeseriesmap
		time_series_individual_map = Object.fromEntries(Object.entries(time_series_individual_map).filter(([key, value]) =>  !(Array.isArray(value) && value.length === 0)));
		
		// build the time series list
		var ccyy_list = time_series_individual_map[CCYY];
		for (var ccyy_index in ccyy_list) {
			var ccyy_record = ccyy_list[ccyy_index];			
			for (var time_series_class_var in time_series_individual_map) {
				if (time_series_class_var == CCYY) {
					continue;
				}				
				var cc_list = time_series_individual_map[time_series_class_var];
				cc_list.sort(compareClassCodeSeq);				
				for (var cc_index in cc_list) {
					var cc_record = cc_list[cc_index];
					var temp_mdt = $.grep(mdt, function (obj) { return (obj[CCYY] == ccyy_record.class_code) && (obj[time_series_class_var] == cc_record.class_code); });
					if (temp_mdt.length > 0) {						
						var record_text = cc_record.def_class_code_desc;
						var display_text = record_text + ' ' + ccyy_record.def_class_code_desc;
						if ((langDir == 'tc/') || (langDir == 'sc/')) {
							display_text = ccyy_record.def_class_code_desc + '年';
							var record_text_last_char = record_text.slice(-1);
							if (time_series_class_var == MM) {
								display_text += record_text;
								if (record_text_last_char != '月') {
									display_text += '月';
								}
							} else if (time_series_class_var == Q) {
								if (record_text_last_char == '季') {
									display_text += record_text;
								} else {
									display_text += '第' + record_text + '季';
								}
							} else {
								display_text += record_text;
							}
                            for (var i = CHINESE_MONTH.length - 1; i >= 0; i--) {
                                if (display_text.indexOf(CHINESE_MONTH[i]) >= 0) {
                                    display_text = display_text.replace(CHINESE_MONTH[i], (i + 1).toString());
                                    break;
                                }
                            }
						}
						if (no_ccyy_tv.includes(time_series_class_var)) {
							display_text = getMMYearString(ccyy_record.class_code, record_text);
						}
						if (time_series_class_var == QoQ) {
							display_text = getQQYearString(ccyy_record.class_code, record_text);
						}
						var time_series_record = {
							ccyy_class_var: CCYY,
							ccyy_record: ccyy_record,
							class_var: time_series_class_var,
							cc_record: cc_record,
							display_text: display_text,
						};
						time_series_list.push(time_series_record);
					}
				}
			}
		}
		if (time_series_list.length == 0) {
			for (var ccyy_index in ccyy_list) {
				var ccyy_record = ccyy_list[ccyy_index];
				var time_series_record = {
					ccyy_class_var: CCYY,
					ccyy_record: ccyy_record,
					class_var: '',
					cc_record: '',
					display_text: ccyy_record.def_class_code_desc,
				};
				time_series_list.push(time_series_record);
			}			
		}		
		// display mdt
		for (var mdt_index in variable_mapping_record.mdt) {
			var mdt_text_record = variable_mapping_record.mdt[mdt_index];
			var mdt_element = document.getElementById(mdt_text_record.element_id);
			if (mdt_element) {
				var current_mdt = mdt;
				var cv_used = ["mdt_theme_id"];				
				var lookup_path = mdt_text_record.mdt_param.slice(0);
				if (mdt_text_record.latest_time_series) {
					 if (mdt_text_record.element_id.toString().endsWith("_CCYY")) {	
						time_series_list = [];
						for (var ccyy_index in ccyy_list) {
						var ccyy_record = ccyy_list[ccyy_index];
						var time_series_record = {
							ccyy_class_var: CCYY,
							ccyy_record: ccyy_record,
							class_var: '',
							cc_record: '',
		     			    display_text: ((langDir === 'tc/' || langDir === 'sc/') 
							? ccyy_record.def_class_code_desc + '年' 
							: ccyy_record.def_class_code_desc),
						  };
						var temp_mdt = $.grep(mdt, function (obj) { return (obj[CCYY] == ccyy_record.class_code) && (obj[time_series_class_var] == ''); });  
						if (temp_mdt.length > 0 )
							time_series_list.push(time_series_record);
						}		
					} 
					
					var temp_time_series_list = time_series_list;
					for (var loopup_index in lookup_path) {
						var loopup_record = lookup_path[loopup_index];
						if (time_series_individual_map[loopup_record.class_var]) {
							var temp_loopup_record_class_code = loopup_record.class_code;
							if (!temp_loopup_record_class_code) {
								temp_time_series_list = $.grep(temp_time_series_list, function (obj) { return (obj['class_var'] != loopup_record.class_var); });
							}
						}
					}					
					
					// remove all other timeseries other than designated tv and CCYY if element suffix is defined
					var tempStr = get_time_series_suffix(mdt_text_record.element_id);
					if (tempStr !='')
						temp_time_series_list = temp_time_series_list.filter(item => item.class_var === "CCYY" || item.class_var === tempStr );
					
					//--
					var latest_time_series = Number(mdt_text_record.latest_time_series);
					var time_series_record = temp_time_series_list[temp_time_series_list.length - 1 - latest_time_series];
					if (time_series_record) {
						lookup_path.push({
							class_var: CCYY,
							class_code: time_series_record.ccyy_record.class_code,
						});
						if (time_series_record.class_var) {
							lookup_path.push({
								class_var: time_series_record.class_var,
								class_code: time_series_record.cc_record.class_code,
							});
						}
						
						var time_series_element = document.getElementById(mdt_text_record.time_series_element_id);
						if (time_series_element) {
							time_series_element.innerHTML = setHTMLforLabel2(time_series_record.display_text);	//setHTMLforLabel(time_series_record.display_text, true);
						}
					} else {
						// no record found
						var sd_record = all_sd_list[na_sd_value];
						var sd_text = sd_record.sd_symbol;
						mdt_element.innerHTML = setHTMLforLabel2(sd_text);	//setHTMLforLabel(sd_text, true);
						continue;
					}
				}
				current_mdt = filterMdtFromLookupPath(current_mdt, lookup_path, cv_used);
				// remove mdt with extra conditions
				var matched_mdt_record = getMdtRecordWithoutExtraCondition(current_mdt, cv_used, null);				
				if (matched_mdt_record) {
					var sd_element = null;
					if (mdt_text_record.sd_element_id) {
						sd_element = document.getElementById(mdt_text_record.sd_element_id);
					}					
					var sd_text = '';
					var sd_values = matched_mdt_record['sd_value'];
					var sd_result = createSdFromListText(all_sd_list, sd_values, sd_text, sd_used_list, null, null);
					sd_text = sd_result.sd_text;
					var suppressed = sd_result.suppressed;
					if (suppressed) {
						mdt_element.innerHTML = setHTMLforLabel2(sd_text);	//setHTMLforLabel(sd_text, true);
					} else {
						//add for custom the index overview statistics
						if (mdt_text_record.element_id =="popn_pop_raw_h_2_mdt_0"){
							var formatValue = mdt_element.getAttribute('format');
							var unitValue = mdt_element.getAttribute('unit');
							if (unitValue == "1000"){
								let strNumber = matched_mdt_record.obs_value;
								let result = parseFloat(strNumber) * 1000;
								matched_mdt_record.obs_value = result;
							}
							if (formatValue !=null){
								current_sp_record.def_separator_format = formatValue;
							}
	
						}
						//
						var inner_html = createObsValueText(matched_mdt_record, current_sp_record, true);
						var outer_html = '';
						if (sd_element) {
							if (all_sd_list[sd_values]) {
								sd_element.innerHTML = setHTMLforLabel2(all_sd_list[sd_values].sd_desc);	//setHTMLforLabel(all_sd_list[sd_values].sd_desc, true);
							}
						} else {
							outer_html = ' ' + sd_text;
						}
						inner_html = inner_html.trim();
						mdt_element.innerHTML = setHTMLforLabel2(inner_html);	//setHTMLforLabel(inner_html, true);
						mdt_element.outerHTML = mdt_element.outerHTML + outer_html;
					}
				}				
			}
		}		
		// display sv text
		for (var sv_index in variable_mapping_record.sv_text) {
			var sv_record = variable_mapping_record.sv_text[sv_index];
			if (sv_record.element_id) {
				var sv_element = document.getElementById(sv_record.element_id);
				if (sv_element) {
					var record_text = sv_record.def_stat_desc;
					record_text = createFootnote(sv_record, record_text, footnote_used_list, null);
					sv_element.innerHTML = setHTMLforLabel2(record_text);	//setHTMLforLabel(record_text, true);
				}
			}
		}		
		// display cc text
		for (var cc_index in variable_mapping_record.cc_text) {
			var cc_record = variable_mapping_record.cc_text[cc_index];
			if (cc_record.element_id) {
				var cc_element = document.getElementById(cc_record.element_id);
				if (cc_element) {
					var record_text = cc_record.def_class_code_desc;
					record_text = createFootnote(cc_record, record_text, footnote_used_list, null);
					cc_element.innerHTML = setHTMLforLabel2(record_text);	//setHTMLforLabel(record_text, true);
				}
			}
		}		
		// display chart
		Highcharts.wrap(Highcharts.Chart.prototype, 'exportChartLocal', function (proceed, options) {
			if (options && options.type === 'application/pdf') {
				this.exportChart(options);
			} else {
				proceed.call(this, options);
			}
		});		
		for (var chart_index in variable_mapping_record.chart) {
			var chart_record = variable_mapping_record.chart[chart_index];
			if (chart_record.element_id) {
				var chart_element = document.getElementById(chart_record.element_id);
				if (chart_element) {
					var chart_record = all_chart_list[chart_record.chart_code];
					buildChart(chart_record, chart_element, true, null);
				}
			}
		}
	}
	// display sd value
	var sd_values_element = document.getElementById('sd_values');
	if ((sd_values_element) && ((sd_used_list.length > 0) || (footnote_used_list.length > 0))) {
		var p_h1 = document.createElement("span");
		p_h1.innerHTML = table_text.notes;
		sd_values_element.appendChild(p_h1);	
		var tbl = document.createElement('table');
		var tbdy = document.createElement('tbody');
		var row_counter = 0;		
		// insert CV / CC / SV / SP footnotes
		for (i = 0; i < footnote_used_list.length; i++) {
			var note_string = footnote_used_list[i];
			var note_counter = i + 1;			
			var cell_counter = 0;
			var row = tbdy.insertRow(row_counter);
			row_counter++;
			var cell_1 = row.insertCell(cell_counter);
			cell_1.classList.add('sd_td');
			cell_1.innerHTML = '<a name="' + note_counter + '" style="text-decoration: none;">' + note_counter + '</a>';
			cell_counter++;
			var cell_2 = row.insertCell(cell_counter);
			cell_2.innerHTML = note_string;
		}		
		for (var sd_index in sd_used_list) {
			var sd_value = sd_used_list[sd_index];
			var sd = all_sd_list[sd_value];
			var sd_desc = sd.sd_desc;
			var sd_sybmol = sd.sd_symbol;			
			var cell_counter = 0;
			var row = tbdy.insertRow(row_counter);
			row_counter++;
			var cell_1 = row.insertCell(cell_counter);
			cell_1.classList.add('sd_td');
			cell_1.innerHTML = '<a name="' + sd_sybmol + '" style="text-decoration: none;">' + sd_sybmol + '</a>';
			cell_counter++;
			var cell_2 = row.insertCell(cell_counter);
			cell_2.innerHTML = sd_desc;
		}		
		tbl.appendChild(tbdy);
		sd_values_element.appendChild(tbl)
	} else {
        var overview_fn = $("#sd_values");
        if (overview_fn && overview_fn.length > 0 && $(overview_fn[0]).html() == "") {
            $(".footer_note_table").css("display", "none");
        }
	}
	if (typeof do_not_build_overview_table === 'undefined') {
		buildOverviewTable();
	}
}

function buildOverviewTable() {
	var overview_element = document.getElementById("overview");
	if (overview_element) {
		var row_counter = 0;
		var tbl = document.createElement('table');
		tbl.id = 'overview_table';
		tbl.style.width = '100%';
		var tbdy = document.createElement('tbody');
		tbl.appendChild(tbdy);
		var last_th_id_list = [];
		for (var child_i = 0; child_i < overview_element.children.length; child_i++) {
			var overview_sub_element = overview_element.children[child_i];
			for (var row_div_i = 0; row_div_i < overview_sub_element.children.length; row_div_i++) {
				var row_div_element = overview_sub_element.children[row_div_i];
				if ((!row_div_element.classList.contains('statistic_result')) && 
					(!row_div_element.classList.contains('statistic_result_1')) &&
					(!row_div_element.classList.contains('statistic_result_2'))) {
					continue;
				}
				$(row_div_element).addClass('original_overview');
				$(row_div_element).addClass('non-printable');
				$(row_div_element).attr("aria-hidden", "true");
				
				var row = tbdy.insertRow(row_counter);
				if (row_div_i == 0) {
					$(row).addClass('overview_table_header');
				} else if (row_div_i % 2 == 0) {
					$(row).addClass('overview_table_1');
				} else {
					$(row).addClass('overview_table_0');
				}				
				row_counter++;
				var cell_counter = 0;
				var row_th_id = null;
				for (var cell_div_i = 0; cell_div_i < row_div_element.children.length ; cell_div_i++) {
					var cell_div_element = row_div_element.children[cell_div_i];
					if (cell_div_element.classList.contains('mobile-container')) {
						continue;
					}
					var cell_1 = null;
					var cell_data = setHTMLforLabel2(cell_div_element.innerHTML);	//setHTMLforLabel(cell_div_element.innerHTML, true);
					if ((cell_data) && ((cell_counter == 0) || (row_div_i == 0))) {
						cell_1 = document.createElement("TH");
						cell_1.id = 'overview_table_' + child_i + '_' + row_div_i + '_' + cell_div_i;
						
						if ((cell_data) && ((cell_counter > 0) || (row_div_i == 0))) {
							last_th_id_list[cell_div_i] = cell_1.id;
						}
						row.appendChild(cell_1);
						
						if (cell_counter == 0) {
							row_th_id = cell_1.id;
						} else {
							$(cell_1).addClass('overview_table_right');
						}
						
						if (row_div_i > 0) {
							cell_1.setAttribute("headers", last_th_id_list[0]);
						}
					} else {
						cell_1 = row.insertCell(cell_counter);
						if (cell_data) {
							cell_1.setAttribute("headers", last_th_id_list[cell_div_i] + ' ' + row_th_id);
						}
						$(cell_1).addClass('overview_table_right');
					}
					
					cell_1.innerHTML = cell_div_element.innerHTML;
					var all_children = cell_1.getElementsByTagName('*');
					for (var all_children_i = 0; all_children_i < all_children.length; all_children_i++) {
						var child_element = all_children[all_children_i];
						if (child_element.id) {
							child_element.id = 'overview_table_' + child_element.id;
						}
					}
					cell_counter++;
				}
			}			
		}
		overview_element.insertBefore(tbl, overview_element.childNodes[0]); 
	}
}

function buildTVCheckboxes(cv_body_div, table_data, cv_record, class_var) {
	var div = document.createElement("div");	
	div.classList.add("cust_cv_container");
	div.classList.add(HIDDEN_CHART_CV_CLASS_NAME);
	div.id = "cust_" + class_var;
	cv_body_div.appendChild(div);
	var p_h = document.createElement("span");				
	var display_text = cv_record.def_class_desc;
	p_h.innerHTML = setHTMLforLabel(display_text);
	p_h.classList.add('cust_ccg_header');
	var br_h = document.createElement("br");
	div.appendChild(p_h);
	div.appendChild(br_h);							
	
//20230620

	if (class_var== CCYY || class_var ==CCYY_F) 
	{
		
		var objMinMaxYear = {min:1985,max:new Date().getFullYear() -1} ;
		var objDefaultRange = {min:2021,max:new Date().getFullYear()-1 } ;
		
		var div2 = document.createElement("div");	
		div2.classList.add('discrete_range');
		div2.classList.add(class_var);
				
		var radio_1 = buildRadioButton( RADIO + '_range_' + class_var ,RADIO + '_range_' + class_var, RADIO + '_tv_view_' + class_var);	
		var radio_2 = buildRadioButton( RADIO + '_discrete_' + class_var,RADIO + '_discrete_' + class_var, RADIO + '_tv_view_' + class_var);
		
		radio_1.setAttribute('aria-label',webtable_textArr[url_lang]['range_view']);
		radio_2.setAttribute('aria-label',webtable_textArr[url_lang]['discrete_view']);
		
		var p_1 = document.createElement("label");
		var p_2 = document.createElement("label");	
		
		p_1.innerHTML = webtable_textArr[url_lang]['range_view'];
		p_2.innerHTML = webtable_textArr[url_lang]['discrete_view'];
		p_1.setAttribute('for', radio_1.id);		
		p_2.setAttribute('for', radio_2.id);
		p_1.classList.add('for_checkbox');
		p_2.classList.add('for_checkbox');
		//cv_position.classList.add('positions');
		div2.appendChild(radio_1);
		div2.appendChild(p_1);
		div2.appendChild(radio_2);
		div2.appendChild(p_2);
		div.appendChild(br_h);	
		div.appendChild(div2);			
		div.appendChild(br_h);	
		
		var div3 = document.createElement("div");
		div3.id  = "discreteview_" + class_var;	
		
		buildSingleCvCheckBox(table_data, cv_record, div3, class_var, objMinMaxYear, objDefaultRange);
				
		var div4 = document.createElement("div");
		div4.id  = "rangeview_" + class_var;
		div.appendChild(div3);			
		div.appendChild(div4);
		
		createsliderOptionBag(class_var);
				
		var tmpLen = sliderOptionBag[class_var].length;
				
		if (tmpLen < minOptionsToShowSlider)
		{
			$(".discrete_range").remove();
			return;		
		}		
		
		
		if (checkIsBookmark())			
			radio_2.setAttribute('checked','checked');
		else
		{
			radio_1.setAttribute('checked','checked');
			 buildTVRangeView(div4,objMinMaxYear,objDefaultRange,class_var);				
			 toggleDiscrete_Range(2,class_var);
		}
		radio_2.addEventListener('click', function() 
			{
			
				toggleDiscrete_Range(1,class_var);
			});
		radio_1.addEventListener('click',function()
			{
			 
			 buildTVRangeView(div4,objMinMaxYear,objDefaultRange,class_var);				
			 toggleDiscrete_Range(2,class_var);
				
			}
		);
		
	}
	else
	{
		buildSingleCvCheckBox(table_data, cv_record, div, class_var);		
	}
	//
	//modified 20230620	
	//buildSingleCvCheckBox(table_data, cv_record, div, class_var);
	
}

function checkIsBookmark() {
	var url = window.location.href;
	if (url.includes("web_table.html") && url.includes("id") && url.includes("param")) {
		return true;
	} else {
		return false;
	}	 
}
 
function createsliderOptionBag(yearMode) {
	//get data from checkboxes 		
	sliderOptionBag[yearMode]= [];	
	var checkboxes = document.querySelectorAll('#discreteview_' + yearMode +' input[type="checkbox"]:not(input[value="' + CCYY +'"]):not(input[value="'+ CCYY_F + '"])');
	var counter = 1 ;		
	for (var cbobj = 0; cbobj<=checkboxes.length-1;cbobj ++ ) {		
		var record = checkboxes[cbobj];	
		let ccid = record.id;	
		let display_text = record.labels[0]?.innerText;
		let checked = record.checked;		
		let singleBox = {
			"sequence" : counter,			
			"ccid" : ccid,
			"display_text" : display_text,
			"checked" : checked
		};
		sliderOptionBag[yearMode].push(singleBox);			
		counter ++; 		
	}		
}

//added 20230620
function get_minmax_year(obj,yearMode) {
	obj.min = 0;	
	obj.max = sliderOptionBag[yearMode].length-1;
}

function get_default_range(obj,yearMode) {
	var selectedRange =  getSelectedYears(yearMode);
	obj.min = selectedRange[0];
	obj.max = selectedRange[1];
}

function buildTVRangeView(container,objMinMaxYear,objDefaultRange,yearMode) {
	$("#rangeview_" + yearMode + " .range").remove();	
	get_minmax_year(objMinMaxYear,yearMode);
	get_default_range(objDefaultRange,yearMode);	
	var divRange = document.createElement("div");
	divRange.classList.add('range');	
	var divRangeSlider = document.createElement("div");
	divRangeSlider.classList.add('range-slider');	
	var spanRangeSelected =	document.createElement("span");
	spanRangeSelected.classList.add('range-selected');	
	divRangeSlider.appendChild(spanRangeSelected);	
	divRange.appendChild(divRangeSlider);	
	var divRangeInput = document.createElement("div");
	divRangeInput.classList.add('range-input');	
	var input1  = document.createElement("input");
	input1.setAttribute('type','range');
	input1.setAttribute('role','slider');	
	input1.classList.add('min');	
	input1.setAttribute('min',objMinMaxYear.min);	
	input1.setAttribute('max',objMinMaxYear.max);	
	input1.setAttribute('aria-valuemin',objMinMaxYear.min);
	input1.setAttribute('aria-valuemax',objMinMaxYear.max);	
	input1.value = objDefaultRange.min;	
	input1.setAttribute('aria-valuenow',objDefaultRange.min);
	input1.setAttribute('aria-valuetext',  webtable_textArr[url_lang]['from'] + sliderOptionBag[yearMode][objDefaultRange.min].display_text);		
	input1.setAttribute('step','1');	
	divRangeInput.appendChild(input1);	
	var input2  = document.createElement("input");
	input2.setAttribute('type','range');	
	input2.setAttribute('role','slider');	
	input2.classList.add('max');
	input2.setAttribute('min',objMinMaxYear.min);	
	input2.setAttribute('max',objMinMaxYear.max);	
	input2.setAttribute('aria-valuemin',objMinMaxYear.min);	
	input2.setAttribute('aria-valuemax',objMinMaxYear.max);		
	input2.value = objDefaultRange.max;
	input2.setAttribute('aria-valuenow',objDefaultRange.max);
	input2.setAttribute('aria-valuetext',  webtable_textArr[url_lang]['to'] + sliderOptionBag[yearMode][objDefaultRange.max].display_text);	
	input2.setAttribute('step','1');	
	divRangeInput.appendChild(input2);	
	divRange.appendChild(divRangeInput);	
	var divRangeLegend = document.createElement('div');
	divRangeLegend.setAttribute('id','rangelegend');	
	var spanRangeMin = document.createElement('span');
	spanRangeMin.classList.add('rangemin');		
	spanRangeMin.innerHTML = sliderOptionBag[yearMode][objMinMaxYear.min].display_text;
	divRangeLegend.appendChild(spanRangeMin);	
	var spanRangeMax = document.createElement('span');
	spanRangeMax.classList.add('rangemax');		
	spanRangeMax.innerHTML = sliderOptionBag[yearMode][objMinMaxYear.max].display_text;	
	divRangeLegend.appendChild(spanRangeMax);		
	divRange.appendChild(divRangeLegend);	
	var divStyleReset = document.createElement('div');
	divStyleReset.style = 'clear: both';
	divRange.appendChild(divStyleReset);	
	var divRangeYear = document.createElement('div');
	divRangeYear.classList.add('range-year');	
	var lblmin = document.createElement('strong');	
	lblmin.innerHTML = webtable_textArr[url_lang]['from'];	
	divRangeYear.appendChild(lblmin);	
	var inputmin = document.createElement('span');	
	inputmin.name = 'min_' + yearMode;
	inputmin.classList.add('sliderRangeInput');
	inputmin.setAttribute('role','textbox');	
	inputmin.innerHTML = sliderOptionBag[yearMode][objDefaultRange.min].display_text;		
	divRangeYear.appendChild(inputmin);	
	var lblmax = document.createElement('strong');		
	lblmax.innerHTML = webtable_textArr[url_lang]['to'];	
	divRangeYear.appendChild(lblmax);	
	var inputmax = document.createElement('span');
	inputmax.classList.add('sliderRangeInput');
	inputmax.name = 'max_' + yearMode;
	inputmax.setAttribute('role','textbox');	
	inputmax.innerHTML = sliderOptionBag[yearMode][objDefaultRange.max].display_text;		
	divRangeYear.appendChild(inputmax);	
	divRange.appendChild(divRangeYear);	
	container.appendChild(divRange);	
	redrawSlider(yearMode);
}

function toggleDiscrete_Range(mode,yearMode) {
	var dv = document.getElementById("discreteview_" + yearMode);
	var rv = document.getElementById("rangeview_" + yearMode);	
	if (typeof dv==='undefined' || dv==null)
		return;
	if (mode==1) {
		dv.style.display ="block";		
		rv.style.display ="none";		
		$(".discrete_range." + yearMode + " #radio_discrete_"+ yearMode).prop('checked',true);
		$(".discrete_range." + yearMode + " #radio_range_"+ yearMode).prop('checked',false);
	}
	if (mode==2) {
		rv.style.display ="block";		
		dv.style.display ="none";		
		$(".discrete_range." + yearMode +" #radio_discrete_" + yearMode).prop('checked',false);
		$(".discrete_range." + yearMode +" #radio_range_" + yearMode).prop('checked',true);		
	}		
}

function getSelectedYears(yearMode) {
  

  // Get an array of the checked checkboxes
  
		
	var checked  = Array.prototype.slice.call(sliderOptionBag[yearMode]).filter(function(checkbox) {
	return checkbox.checked;
	});
	

  // If no checkboxes are checked, return the last 1 selectable year
  if (checked.length === 0) {
    
	var last_index = sliderOptionBag[yearMode].length-1;
	
    return [last_index, last_index];
  }

  // If only one checkbox is checked, return the checked year twice
  if (checked.length === 1) {
	
	var year = checked[0].sequence -1 ;
	
    return [year, year];
  }

  // If more than one checkbox is checked, return the earliest and latest year
  var years = checked.map(function(checkbox) {
    
	return (checkbox.sequence-1);
  });
  
  var beginIndex  = Math.min.apply(null,years);
  var endIndex  = Math.max.apply(null,years);
  
  return [beginIndex, endIndex];
}

function overrideSliderValues(yearMode) {	
	createsliderOptionBag(yearMode);	
	redrawSlider(yearMode);
}

function redrawSlider(yearMode, tvRange) {
	// define the operation and events for the slider -
	let rangeMin = 0;
	const range = document.querySelector("#rangeview_" + yearMode +  " .range-selected");
	const rangeInput = document.querySelectorAll("#rangeview_" + yearMode +  " .range-input input");
	const rangeYear=  document.querySelectorAll("#rangeview_" + yearMode + " .range-year .sliderRangeInput");
	const rangeLegend = document.querySelectorAll("#rangeview_" + yearMode +  " #rangelegend")[0];
	const rangeSlider = document.querySelectorAll("#rangeview_" + yearMode +  " .range-slider")[0];
	if (typeof rangeInput[0] === 'undefined')
		return ;
	//let minRange = parseInt(rangeInput[0].value);
	//let maxRange = parseInt(rangeInput[1].value);    	
	var objMinMaxYear = {min:0,max:0};
	var objSelectedYear = {min:0,max:0};
	get_minmax_year(objMinMaxYear,yearMode);
	if (tvRange) {
		objSelectedYear.min = tvRange[0];
		objSelectedYear.max = tvRange[1];
	} else {
		get_default_range(objSelectedYear,yearMode);
	}
	let minRange = objSelectedYear.min;
	let maxRange = objSelectedYear.max;	
	rangeInput[0].value = minRange;
	rangeInput[1].value = maxRange;	
	rangeInput[0].setAttribute('aria-valuenow',minRange);		
	rangeInput[1].setAttribute('aria-valuenow',maxRange);
	if (objMinMaxYear.max==0)
		rangeInput[1].style.direction = 'rtl';	
	rangeYear[0].innerHTML = sliderOptionBag[yearMode][minRange].display_text;
	rangeYear[1].innerHTML = sliderOptionBag[yearMode][maxRange].display_text;	
	rangeInput[0].setAttribute('aria-valuetext',  webtable_textArr[url_lang]['from'] + sliderOptionBag[yearMode][minRange].display_text);
	rangeInput[1].setAttribute('aria-valuetext',  webtable_textArr[url_lang]['to'] + sliderOptionBag[yearMode][maxRange].display_text);	
	if (objMinMaxYear.max==0)
		var indentPercent = 0; 
	else
		var indentPercent = 4;
	rangeInput[1].style.marginLeft = indentPercent + "%";		
	rangeLegend.style.width = (100 + indentPercent) + "%";
	rangeSlider.style.width = (100 + indentPercent) + "%";	
	if (objMinMaxYear.max==0) {
		range.style.left = "0%";
		range.style.right = "0%";
	} else {
		range.style.left = (minRange - rangeInput[0].min)/ (rangeInput[1].max - rangeInput[0].min) * (100 - indentPercent) + "%";	
		range.style.right = (rangeInput[1].max -maxRange) / (rangeInput[1].max - rangeInput[0].min ) * (100-indentPercent )  + "%";		
	}	
	rangeInput.forEach((input) => {
		input.addEventListener("input", (e) => {
			let minRange = parseInt(rangeInput[0].value);
			let maxRange = parseInt(rangeInput[1].value);
			if (maxRange - minRange < rangeMin ) {     
				if (e.target.className === "min") {
					rangeInput[0].value = maxRange - rangeMin;        
				} else {
					rangeInput[1].value = minRange + rangeMin;        
				}		   
				range.style.left = (parseInt(rangeInput[0].value) - rangeInput[0].min)/ (rangeInput[1].max - rangeInput[0].min) * (100 - indentPercent) + "%";
				range.style.right = (rangeInput[1].max -parseInt(rangeInput[1].value)) / (rangeInput[1].max - rangeInput[0].min ) * (100-indentPercent )  + "%";
					rangeYear[0].innerHTML = sliderOptionBag[yearMode][parseInt(rangeInput[0].value)].display_text;
					rangeYear[1].innerHTML = sliderOptionBag[yearMode][parseInt(rangeInput[1].value)].display_text;
			} else {
				/* var currentValue = parseInt(e.target.value);
				var increment  = 0.1 ;
				e.target.value = currentValue + increment;	 */				
				rangeYear[0].innerHTML = sliderOptionBag[yearMode][minRange].display_text;
				rangeYear[1].innerHTML = sliderOptionBag[yearMode][maxRange].display_text;
				rangeInput[0].setAttribute('aria-valuenow',minRange);		
				rangeInput[1].setAttribute('aria-valuenow',maxRange);
				rangeInput[0].setAttribute('aria-valuetext',  webtable_textArr[url_lang]['from'] + sliderOptionBag[yearMode][minRange].display_text);
				rangeInput[1].setAttribute('aria-valuetext',  webtable_textArr[url_lang]['to'] + sliderOptionBag[yearMode][maxRange].display_text);
				range.style.left = (minRange - rangeInput[0].min)/ (rangeInput[1].max - rangeInput[0].min) * (100 - indentPercent) + "%";				
				range.style.right = (rangeInput[1].max -maxRange) / (rangeInput[1].max - rangeInput[0].min ) * (100-indentPercent )  + "%";
			}
			overrideCheckboxValues(yearMode);
			createsliderOptionBag(yearMode);
		});
	});
}

function overrideCheckboxValues(yearMode) {	
	const rangeInput = document.querySelectorAll("#rangeview_" + yearMode + " .range-input input");	
	if (typeof rangeInput[0] === 'undefined')
		return;	
	var startYear =  parseInt(rangeInput[0].value);
	var endYear = parseInt(rangeInput[1].value);
	//set the all checkbox to uncheck first 	
	$('#discreteview_' + yearMode +' input[type="checkbox"]:input[value="' + yearMode +'"]').prop('checked',false);	
	//$('#discreteview input[type="checkbox"]:input[value="'+ CCYY_F +'"]').prop('checked',false);	
	//if start year = range min and end year is range max then set the all checkbox to on
	var rangemin = 0;		
	var rangemax = sliderOptionBag[yearMode].length-1;		
	if (startYear == rangemin && endYear == rangemax) {		
		$('#discreteview_' + yearMode +' input[type="checkbox"]:input[value="'+ yearMode +'"]').each(function() {
			this.click();
		});		
		return;
	}	
	//for each checkboxes compare it with the range , if falls in the range then set checked = true 	
	var counter = 0;
	$('#discreteview_' + yearMode + ' input[type="checkbox"]:not(input[value="'+ yearMode +'"])').each(function() {
		// Get the year value from the label		    
		var year = sliderOptionBag[yearMode][counter].sequence-1; 
		//console.log(year);
		$(this).prop('checked', false);
		// Check if the year is within the range
		if (year >= startYear && year <= endYear) {
			// Set the checkbox to selected
			$(this).prop('checked', true);
		}
		counter++;
	});		
}

//end added 20230620

// build classification check box
function buildTvCheckBox(table_data, cv_body_div) {
	var non_tv_cvs = [];
	var cv_ccyy = table_data.lang_data.cv_list[CCYY];
	if (cv_ccyy) {
		buildTVCheckboxes(cv_body_div, table_data, cv_ccyy, CCYY);
	}
	for (var class_var in table_data.lang_data.cv_list) {
		var cv_record = table_data.lang_data.cv_list[class_var];	
		if (cv_record.is_time_series === "1") {
			if (class_var !== CCYY) {
				buildTVCheckboxes(cv_body_div, table_data, cv_record, class_var);
			}
		} else {
			non_tv_cvs.push({
				class_var: class_var,
				cv: table_data.lang_data.cv_list[class_var]
			});
		}				
	}
	return non_tv_cvs;
}
function buildCvCheckBox(table_data) {
	var checkbox_element = document.getElementById('classificationCheckBoxes');
	if (checkbox_element) {		
		var used_cvs = [];
		var use_tv = false;
		for (var c in table_data.chart_data) {
			var chart = table_data.chart_data[c];
			use_tv = use_tv || chart.x_axis.is_time_series;
			used_cvs.push(chart.x_axis.class_var);
			chart.y_axis.setting.forEach(function (y) {
				if (y.class_var) {
					if (table_data.lang_data.cv_list[y.class_var].is_time_series) {
						use_tv = true;
					}
					if (!used_cvs.includes(y.class_var)) {
						used_cvs.push(y.class_var);
					}
				}				
			});
		}
		used_cvs = used_cvs.filter(function (v) { return v; });
		var cv_body_div = buildCvHeaderRadioButton(table_data, table_text.tv, TS_INDEX, checkbox_element, (use_tv ? null : HIDDEN_CHART_CV_CLASS_NAME), "cust_tv");
		var non_tv_cvs = buildTvCheckBox(table_data, cv_body_div);
		removeHiddenChartClass(table_data, checkbox_element, non_tv_cvs, used_cvs);
	}	
}
function removeHiddenChartClass(table_data, checkbox_element, non_tv_cvs, used_cvs) {
	non_tv_cvs.forEach(function (cv) {	
		var hidden_chart_cv_cc_class = '';
		if (!used_cvs.includes(cv.class_var)) {
			hidden_chart_cv_cc_class = HIDDEN_CHART_CV_CLASS_NAME;
		}
		var cv_body_div = buildCvHeaderRadioButton(table_data, cv.cv.def_class_desc, cv.cv.cv_index, checkbox_element, hidden_chart_cv_cc_class, "cust_" + cv.class_var);
		buildSingleCvCheckBox(table_data, cv.cv, cv_body_div, cv.class_var);
	});
}
function findPACIDs(id, pac) {
	return pac.filter(function (f) {
		return f.cc_index && f.children && f.children.includes(id);
	})[0];
}

function buildPACCheckBox(div_element, table_data, class_var, pac, ids, level, chart_used_cc, checkbox_id_list, current_checkbox_id_list, all_show, counter, result) {
	if (!result) {
		result = {
			non_hidden: [],
			child_checked: false
		};
	}
	var temp = [];
	if (!ids) {
		ids = pac.filter(function (f) { return !f.parent_id }).sort(compareClassCodeSeq);
		chart_used_cc.forEach(function (c) {
			c.cc_list.forEach(function (cc) {
				var itm = pac.filter(function (f) { 
					return f.class_code_group === c.class_code_group && f.class_code === cc;
				})[0];
				if (itm) {
					result.non_hidden.push(itm.id);
					temp.push(itm.id);
				}
			});
		});
		temp.forEach(function (v) {
			var root = v;
			do {
				var itm = findPACIDs(root, pac);
				if (itm) {
					if (result.non_hidden.includes(itm.id)) {
						 root = null;
					} else {
						result.non_hidden.push(itm.id);
						root = itm.id;
					}
				} else {
					root = null;
				}
			} while (root);
		});
	}
	ids.filter(function (v) { return !v.not_pac; }).forEach(function (v) {
		result.child_checked = result.child_checked || (v.show && v.has_data);
		var checkbox_div_element = null;
		var checkbox = null;
		var label_p = document.createElement("label");
		var checkbox_div_element_1 = document.createElement("div");
		if (v.cc_index) {
			checkbox = document.createElement("input");   
			checkbox.value = v.cc_index;
			checkbox.type = "checkbox";
			var checkbox_id = CC + "_" + v.cc_index;
			checkbox.id = checkbox_id;
			checkbox.checked = v.show && v.has_data;
			checkbox_div_element_1.appendChild(checkbox);
			checkbox_id_list.push(checkbox_id);
			current_checkbox_id_list.push(checkbox_id);
			counter.result++;			
			(function (local_table_data, local_pac){
				checkbox.onclick = function() {
					if ($(this).is(":checked")) {
						setCcParentCheck(local_table_data, local_pac, v.id);
					} else {
						setCcParentUncheck(local_table_data, local_pac, v.id);
					}						
					reviseCheckAllCheckBoxStatus($(this).is(":checked"), v.class_var);
				}
			})(table_data, pac);
			label_p.setAttribute('for', checkbox_id);
		/*} else {
			checkbox_div_element_1.innerHTML = "&nbsp;&nbsp;&nbsp;";
			label_p.classList.add("no_checkbox_cc");
		}*/
			label_p.classList.add('for_checkbox');
			label_p.innerHTML = setHTMLforLabel(' ' + v.def_class_code_desc);
			checkbox_div_element = document.createElement("div");
			checkbox_div_element.classList.add(CDM_CHECKBOX_CLASS_NAME);
			checkbox_div_element.classList.add('col-md-12');
			if (level > 0) {
				checkbox_div_element.style.textIndent = (level * 3) + 'em';
			}
			checkbox_div_element.appendChild(checkbox_div_element_1);
			checkbox_div_element.appendChild(label_p);
			div_element.appendChild(checkbox_div_element);
		}
		if (v.children && v.children.length > 0) {
			result = buildPACCheckBox(div_element, table_data, class_var, pac, pac.filter(function (f) { return v.children.includes(f.id); }), level + 1, chart_used_cc, checkbox_id_list, current_checkbox_id_list, all_show, counter, result);
		}
		if (checkbox) {
			checkbox.checked = result.child_checked;
		}
		//if (checkbox_div_element && result.child_hidden && hidden_flag) {	//chart use the parent class_code only
		if (checkbox_div_element && !result.non_hidden.includes(v.id)) {	//chart use the parent class_code only
			checkbox_div_element.classList.add(HIDDEN_CHART_CV_CC_CLASS_NAME);
		}
		all_show = all_show && result.child_checked;
	});
	return result;
}

function buildSingleCvCheckBox(table_data, cv_record, checkbox_element, class_var, objMinMaxYear, objDefaultRange) {
	var all_show = true;
	var current_checkbox_id_list = [];
	var div_element = document.createElement("div");
	div_element.classList.add('row');
	checkbox_element.appendChild(div_element);	
	var temp_ccg_list = cv_record.ccg_list;
	//var ccg_list_length = 0;
	var cv_total_desc = table_text.total;
	if (!cv_record.pac_list || cv_record.pac_list.length <= 0) {
		for (var ccg_index in temp_ccg_list) {
			var ccg = temp_ccg_list[ccg_index];
			if (ccg.total_desc) {
				cv_total_desc = ccg.total_desc;
				break;
			}
			//ccg_list_length++;
		}
	} else {
		cv_total_desc = table_text.grandTotal;
	}
	var cc_checkbox_count = 0;
	var has_pac_list = cv_record.pac_list.length > 0;
	var chart_used_cc = getChartUsedCC(table_data, class_var);			
	if (has_pac_list) {
		var pac = buildPacList(table_data, class_var);
		var counter = { result: 0 };
		buildPACCheckBox(div_element, table_data, class_var, pac, null, 0, chart_used_cc, checkbox_id_list, current_checkbox_id_list, all_show, counter);
		cc_checkbox_count = counter.result;
	} else {
		for (var ccg_index in temp_ccg_list) {
			var temp_ccg_record = temp_ccg_list[ccg_index];
			var chart_matched_cv = chart_used_cc.filter(function (f) { return f.class_code_group === ccg_index; }).length > 0;
			var hidden_chart_cv_cc_class = chart_matched_cv ? '' : HIDDEN_CHART_CV_CC_CLASS_NAME;		
			var temp_cc_list = temp_ccg_record.cc_list;
			var temp_cc_record_list = [];
			for (var class_code in temp_cc_list) {
				var cc_record = temp_cc_list[class_code];
				cc_record.class_code = class_code;
				temp_cc_record_list.push(cc_record);
			}
			temp_cc_record_list.sort(compareClassCodeSeq);			
			/*if (ccg_list_length > 1 && temp_ccg_record.ccg_desc != null) {
				var p = document.createElement("span");
				p.innerHTML = temp_ccg_record.ccg_desc;				
				var checkbox_div_element = document.createElement("div");
				checkbox_div_element.classList.add('cust_ccg_header');
				checkbox_div_element.classList.add('col-md-12');
				checkbox_div_element.appendChild(p);
				div_element.appendChild(checkbox_div_element);
			}*/
			//added 20230620
			if (class_var== CCYY || class_var == CCYY_F)
			{
				if (temp_cc_record_list.length>0)
				{
						objMinMaxYear.min = temp_cc_record_list[0].class_code;
						objMinMaxYear.max = temp_cc_record_list[temp_cc_record_list.length-1].class_code;
						table_data.tv_range = [parseInt(temp_cc_record_list[0].class_code), parseInt(temp_cc_record_list[temp_cc_record_list.length-1].class_code)];
				}			

				let minShow = 0;
				let maxShow = 0 ;
				let numOfShow = 0;
				let preShow = false; 
				
				
				for (var cci in temp_cc_record_list) {
					let cc_recordi = temp_cc_record_list[cci];
					let class_codei = cc_recordi.class_code;				
					 
					if (cc_recordi.show )
					{
						if (numOfShow == 0 )
						{	
							minShow = class_codei;
							maxShow = class_codei;
						}
						else
						{
							if (preShow == true)
							{
								maxShow = class_codei;  
							}
							else
								maxShow = 0;
						}							
						
						preShow = true;
						numOfShow++;	
					}		
					else
					{
						preShow = false;		
					}
				
				}				
				
				if (minShow > 0 && maxShow > 0 )
				{
					objDefaultRange.min = minShow;
					objDefaultRange.max = maxShow;
				}
			}
			//
			//var tmpBuildCCList = table_data.component_data.rev_chrono && cv_record.is_time_series === "1" ? clone(temp_cc_record_list).reverse() : temp_cc_record_list;
			var tmpBuildCCList = temp_cc_record_list;
			for (var c_i in tmpBuildCCList) {
				var cc_record = tmpBuildCCList[c_i];
				var class_code = cc_record.class_code;				
				var hidden_chart_cc_class = hidden_chart_cv_cc_class;
				if (chart_used_cc.filter(function (f) { return f.class_code_group === ccg_index && f.cc_list.includes(class_code); }).length === 0) {
					hidden_chart_cc_class = HIDDEN_CHART_CV_CC_CLASS_NAME;
				}				
				if (cc_record.has_data && cc_record.cc_index) {
					var cc_index = cc_record.cc_index;
					var checkbox = document.createElement("input");
					checkbox.value = (cc_index);
					checkbox.type = "checkbox";
					var checkbox_id = CC + "_" + cc_index;
					checkbox.id = checkbox_id;
					checkbox_id_list.push(checkbox_id);
					current_checkbox_id_list.push(checkbox_id);
					var label_p = document.createElement("label");					
					var display_text = cc_record.def_class_code_desc;
					if (no_ccyy_tv.includes(class_var)) {
						display_text = display_text.replace(/\/\[YYYY\]/g, '').replace(/\/\[YYYY-1\]/g, '');
					}
					if (class_var == QoQ) {
						display_text = display_text.replace(/\[YYYY\]/g, '').replace(/\[YYYY-1\]/g, '');
					}						
					label_p.setAttribute('for', checkbox_id);
					label_p.classList.add('for_checkbox');
					label_p.innerHTML = setHTMLforLabel(' ' + display_text);
					var checkbox_div_element = document.createElement("div");
					checkbox_div_element.classList.add(CDM_CHECKBOX_CLASS_NAME);
					if (hidden_chart_cc_class) {
						checkbox_div_element.classList.add(hidden_chart_cc_class);
					}
					checkbox_div_element.classList.add('col-md-3');					
					checkbox.checked = cc_record.show;
					all_show = all_show && cc_record.show;
					(function (local_table_data, class_var, local_checkbox_id){
						checkbox.onclick = function() {
							var local_checkbox_element = document.getElementById(local_checkbox_id);
							var new_status = local_checkbox_element.checked;							
							reviseCheckAllCheckBoxStatus(new_status, class_var);
						}
					})(table_data, class_var, checkbox_id);
					var checkbox_div_element_1 = document.createElement("div");
					checkbox_div_element.appendChild(checkbox_div_element_1);
					checkbox_div_element_1.appendChild(checkbox);
					checkbox_div_element.appendChild(label_p);
					div_element.appendChild(checkbox_div_element);
					cc_checkbox_count++;
				}
			}
		}
	}	
	if (cc_checkbox_count > 0) {		
		var cv_show_total = 0;
		if (cv_record.is_time_series != '1'){
			//var first_ccg = getFirstCCGForTotal(table_data, class_var);
			var lst = table_data.component_data.table_component_ccg_list[class_var].ccg_list
			for (var ccg_j in lst) {
				//if (first_ccg === lst[ccg_j].class_code_group) {
					lst[ccg_j].cv_total_show = parseInt(lst[ccg_j].show_total);
					if (lst[ccg_j].cv_total_show > 0) {					
						cv_show_total = 1;
					}
				//}
			}
		}
		if (cv_show_total > 0) {
			var total_checkbox = document.createElement("input");   
			total_checkbox.value = (class_var);
			total_checkbox.type="checkbox";
			var total_checkbox_id = CV + "_total_" + class_var;
			total_checkbox.id = total_checkbox_id;
			total_checkbox.classList.add("total_checkbox");
			var p = document.createElement("label");
			p.setAttribute('for', total_checkbox_id);
			p.classList.add('for_checkbox');
			p.innerHTML = setHTMLforLabel(' ' + cv_total_desc);
			var checkbox_div_element = document.createElement("div");
			checkbox_div_element.classList.add(CDM_CHECKBOX_CLASS_NAME);
			checkbox_div_element.classList.add(HIDDEN_CHART_CV_CC_CLASS_NAME);
			if (has_pac_list) {
				checkbox_div_element.classList.add('col-md-12');
			} else {
				checkbox_div_element.classList.add('col-md-3');
			}			
			total_checkbox.checked = true;
			(function (local_table_data, class_var, local_checkbox_id){
				total_checkbox.onclick = function() {
					var local_checkbox_element = document.getElementById(local_checkbox_id);
					var new_status = local_checkbox_element.checked;					
					reviseCheckAllCheckBoxStatus(new_status, class_var);
				}
			})(table_data, class_var, total_checkbox_id);
			if (cv_record.pac_list && cv_record.pac_list.length > 0 && table_data.component_data.pac_mode === "0") {
				total_checkbox.classList.add("pac_total");
			}
			var checkbox_div_element_1 = document.createElement("div");
			checkbox_div_element.appendChild(checkbox_div_element_1);
			checkbox_div_element_1.appendChild(total_checkbox);
			checkbox_div_element.appendChild(p);
			div_element.appendChild(checkbox_div_element);
			checkbox_id_list.push(total_checkbox_id);
			current_checkbox_id_list.push(total_checkbox_id);
		}
		var all_checkbox = document.createElement("input");   
		all_checkbox.value=(class_var);
		all_checkbox.type="checkbox";
		var all_checkbox_id = CV_ALL + "_" + class_var;
		all_checkbox.id = all_checkbox_id;
		if (cv_record.is_time_series !== "1") {
			all_checkbox.classList.add("cv_all_checkbox");
		}
		var p = document.createElement("label");
		p.setAttribute('for', all_checkbox_id);
		p.classList.add('for_checkbox');
		p.innerHTML = setHTMLforLabel(' ' + table_text.all);
		var checkbox_div_element = document.createElement("div");
		checkbox_div_element.classList.add(CDM_CHECKBOX_CLASS_NAME);
		if (has_pac_list) {
			checkbox_div_element.classList.add('col-md-12');
		} else {
			checkbox_div_element.classList.add('col-md-3');
		}		
		all_checkbox.checked = all_show;
		all_checkbox.onclick = function() {
			var new_status = all_checkbox.checked;
			selectCvAll(class_var, new_status);
		}
		var checkbox_div_element_1 = document.createElement("div");
		checkbox_div_element.appendChild(checkbox_div_element_1);
		checkbox_div_element_1.appendChild(all_checkbox);
		checkbox_div_element.appendChild(p);
		div_element.appendChild(checkbox_div_element);
		checkbox_id_list.push(all_checkbox_id);
	}	
	checkbox_id_map[class_var] = current_checkbox_id_list;
}

function checkChildHideCc(cc_record_list, class_code, chart_hide_list, chart_show_list) {
	if (chart_hide_list.indexOf(class_code) >= 0) {
		return false;
	}
	if (chart_show_list.indexOf(class_code) >= 0) {
		return true;
	}
	var result = false;
	var pac_cc_record = cc_record_list[class_code];
	for (var child_index in pac_cc_record.children) {
		var child_class_code = pac_cc_record.children[child_index];
		if ((child_class_code) && (child_class_code != class_code)) {
			result = result || checkChildHideCc(cc_record_list, child_class_code, chart_hide_list, chart_show_list);
		}
	}
	return result;
}

function setTableDataFromUrl(table_data) {
	// load parameters
	var href = window.location.href;
	var clean_url_parameters_map = generateCurrentSelectionUrl(table_data);
	table_data.original_url_parameters_map = clean_url_parameters_map;
	if (url_vars['param']) {
		var compressed_parameters = url_vars['param'];
		var decompressed_parameters = LZString.decompressFromEncodedURIComponent(compressed_parameters);		
		var url_parameters_map = JSON.parse(decompressed_parameters);
		setTableDataFromUrlParameter(table_data, url_parameters_map);		
		if (url_vars[no_popup] != 'true') {
			table_data.original_url_parameters_map = url_parameters_map;
			if ((typeof(idds) != 'undefined') && (idds)) {
				// do nothing here
			} else {
				option_popup = true;
			}
		} else {
			var parameter_index = href.indexOf('?');
			if (parameter_index >= 0) {
				href = href.substring(0, parameter_index);
			}
			var new_url = href + "?id=" + table_data.table_id;
			window.history.replaceState("", table_data.table_title_string, new_url);
		}
		if (url_vars["show_default_btn"] === "true") {
			$("#full_series_button").hide();
			$("#default_series_button").show();
		}
	}
}

function setTableDataFromUrlParameter(table_data, url_parameters_map) {
	// calculate the number of bits available for safe characters
	var character_safe_bit_length = calculateSafeCharactersBits();	
	var has_latest_time_series_record = url_parameters_map[LATEST];	
	var is_reverse = url_parameters_map[IS_REVERSE];
	// build CCYY, No CCYY TV list for No CCYY TV special handling
	var ccyy_list = [];
	var no_ccyy_list = [];
	table_data.component_data.ori_rev_chrono = is_reverse;
	if (table_data.component_data.rev_chrono !== is_reverse) {
		table_data.component_data.rev_chrono = is_reverse;
	}
	checkTvSortingRadio(table_data);
	// cv data
	for (var class_var in url_parameters_map[CV]) {
		var cv_parameter = url_parameters_map[CV][class_var];		
		// special handling for No CCYY TV
			for (var param_index in cv_parameter) {				
				// set the position, ROW / COLUMN
				if (param_index == POSITION) {
					table_data.component_data.table_component_ccg_list[class_var].cv_position = cv_parameter[POSITION];
				} else if (param_index == DISPLAY_ORDER) {
					table_data.component_data.table_component_ccg_list[class_var].display_order = cv_parameter[DISPLAY_ORDER];
				} else if (param_index == SHOW_TOTAL) {
					var cv_total_show = parseInt(cv_parameter[SHOW_TOTAL])
					for (var ccg_i in table_data.component_data.table_component_ccg_list[class_var].ccg_list) {
						if ((typeof(idds) != 'undefined') && (idds)) {
							table_data.component_data.table_component_ccg_list[class_var].ccg_list[ccg_i].show_total = cv_total_show ? 1 : 0;
						}
						table_data.component_data.table_component_ccg_list[class_var].ccg_list[ccg_i].cv_total_show = cv_total_show;
					}
				} else {
					// else set the ccg's cc show					
					var temp_ccg_list = table_data.lang_data.cv_list[class_var].ccg_list;
					for (var ccg_index in temp_ccg_list) {
						var temp_cc_map = temp_ccg_list[ccg_index].cc_list;
						var parameter_value = cv_parameter[ccg_index];
						var byte_value = 0;
						var bit_counter = 0;						
						var temp_cc_list = [];
						var cc_keys = [];
						for (var cc_index in temp_cc_map) {
							cc_keys.push(cc_index);
						}
						//Yuk updated on 19/10/2021 Fixed avoid the incorrect sorting for month as string as table 29 show full series and default series
						cc_keys.sort(sortAlphaNum);
						for (var cc_key in cc_keys) {
							var cc_index = cc_keys[cc_key];
							var cc_record = temp_cc_map[cc_index];
							temp_cc_list.push(cc_record);
						}				
						var last_cc_record_index = null;						
						for (var i in temp_cc_list) {
							var cc_record = temp_cc_list[i];
							cc_record.show = false;
						}						
						for (var i in temp_cc_list) {
							var cc_record = temp_cc_list[i];							
							bit_counter = i % character_safe_bit_length;
							if (bit_counter == 0) {
								// get new byte
								if (parameter_value.length == 0) {
									break;
								}								
								var current_cv = parameter_value.substring(parameter_value.length - 1);
								parameter_value = parameter_value.substring(0, parameter_value.length - 1);
								byte_value = SAFE_CHARACTERS.indexOf(current_cv);
							}							
							cc_record.show = (((byte_value >> bit_counter) % 2) == 1);
							if ((typeof(idds) != 'undefined') && (idds)) {
								if (cc_record.show) {
									cc_record.default_hide = '0';
								} else {
									cc_record.default_hide = '1';
								}
							}							
						}						
						temp_cc_list.sort(compareClassCodeSeq);
						for (var i in temp_cc_list) {
							var cc_record = temp_cc_list[i];
							if (cc_record.show) {
								last_cc_record_index = i;
							}
						}						
						// for records that are after the url show records, set them to show if the original url set latest record to show
						if (indenpendent_tv_list.includes(class_var) && last_cc_record_index != null && has_latest_time_series_record) {
							var reach_original_last = false;
							for (var i in temp_cc_list) {
								if (last_cc_record_index == i) {
									reach_original_last = true;
								}
								
								if (reach_original_last) {
									var cc_record = temp_cc_list[i];
									if (cc_record.has_data) {
										cc_record.show = true;
									}
								}
								
							}
						}
					} // end for ccg list
				}	// end else position
			}	// end for cv_parameter
	}
	// sv, sp data
	table_data.component_data.sv_position = url_parameters_map[SV][POSITION];
	for (var sv_index in table_data.component_data.table_component_list) {
		var comp_sv_record = table_data.component_data.table_component_list[sv_index];
		var stat_var = comp_sv_record.stat_var;
		var stat_pres = comp_sv_record.stat_pres;		
		var show = false;
		if (url_parameters_map[SV][stat_var]) {
			var sp_list = url_parameters_map[SV][stat_var];
			if (sp_list.indexOf(stat_pres) >= 0) {
				show = true;
			}
		}		
		table_data.lang_data.sv_list[stat_var].sp_list[stat_pres].show = show;
	}
}

function setUiComponent(table_data, ignore_display) {
	var sv_radio_id = getSvRadioButtonValueName(SV, table_data.component_data.sv_position);
	var sv_radio = document.getElementById(sv_radio_id);
	if (sv_radio) {
		sv_radio.checked = true;
	}
	for (var class_var in table_data.component_data.table_component_ccg_list) {
		var comp_cv_record = table_data.component_data.table_component_ccg_list[class_var];		
		var cv_index = table_data.cv_index_map[class_var];
		var cv_record = table_data.cv_map[cv_index];		
		if (no_ccyy_tv.includes(class_var)) {
			continue;
		}		
		// special handling for time series cv radio button
		if (cv_record.is_time_series == 1) {
			cv_index = TS_INDEX;
		}		
		var cv_radio_id = getCvRadioButtonValueName(CV + '_' + cv_index, comp_cv_record.cv_position);
		var cv_radio = document.getElementById(cv_radio_id);
		if (cv_radio) {
			cv_radio.checked = true;
		}
	}	
	setCvCheckBoxFromTableData(table_data, ignore_display);
	setSvSpCheckBoxFromTableData(table_data);
}

function buildMapCombobox() {
	var i;
	for (i = 0; i < table_id_list.length; i++) {
		var table_id = table_id_list[i];
		var table_data = table_data_list[table_id];
		if (!table_data.ccyy_time_series_map_done) {
			return;
		}
	}	
	var map_ccyy_time_series_map = [];
	var map_ccyy_list = [];
	for (i = 0; i < table_id_list.length; i++) {
		var table_id = table_id_list[i];
		var table_data = table_data_list[table_id];
		
		if (i == 0) {
			map_ccyy_time_series_map = table_data.ccyy_time_series_map;
			map_ccyy_list = table_data.ccyy_list;
		} else {
			for (var class_var in map_ccyy_time_series_map) {
				if (table_data.ccyy_time_series_map[class_var]) {
					for (var ccyy_index in map_ccyy_time_series_map[class_var]) {
						if (table_data.ccyy_time_series_map[class_var][ccyy_index]) {
							for (var class_code in map_ccyy_time_series_map[class_var][ccyy_index]) {
								if (table_data.ccyy_time_series_map[class_var][ccyy_index][class_code]) {
									var ccyy_time_series_record_1 = map_ccyy_time_series_map[class_var][ccyy_index][class_code];
									var ccyy_time_series_record_2 = table_data.ccyy_time_series_map[class_var][ccyy_index][class_code];
									
								} else {
									delete map_ccyy_time_series_map[class_var][ccyy_index][class_code];
								}
							}
						} else {
							delete map_ccyy_time_series_map[class_var][ccyy_index];
						}
					}
				} else {
					delete map_ccyy_time_series_map[class_var];
				}
			}			 
			for (var ccyy_index in map_ccyy_list) {
				if (table_data.ccyy_list[ccyy_index]) {
					var ccyy_record = map_ccyy_list[ccyy_index];
				} else {
					delete map_ccyy_list[ccyy_index];
				}
			}
		}
	}
	var dc_time_category_element = document.getElementById('dc-time-category');
	if (dc_time_category_element) {
		$("#dc-time-category").empty();
		time_category_value_map = [];
		var time_category_value_counter = 0;
		var has_map_ccyy_time_series_map = false;		
		// build time series
		time_category_value_year_only = false;
		for (var class_var in map_ccyy_time_series_map) {
			for (var ccyy_index in map_ccyy_time_series_map[class_var]) {
				for (var class_code in map_ccyy_time_series_map[class_var][ccyy_index]) {
					var ccyy_time_series_record = map_ccyy_time_series_map[class_var][ccyy_index][class_code];
					has_map_ccyy_time_series_map = true;
					ccyy_time_series_record.class_var = class_var;
					ccyy_time_series_record.class_code = class_code;					
					time_category_value_map[time_category_value_counter] = ccyy_time_series_record;
					var opt = document.createElement('option');
					opt.value = time_category_value_counter;					
					var error_message = 'At least 1 Statistics option should be selected among all choice of Statistics';
					if (table_data.lang == TC) {
						opt.innerHTML = setHTMLforLabel(ccyy_time_series_record.ccyy_record.def_class_code_desc + '年' + ccyy_time_series_record.time_series_record.def_class_code_desc + '月');
					} else if (table_data.lang == SC) {
						opt.innerHTML = setHTMLforLabel(ccyy_time_series_record.ccyy_record.def_class_code_desc + '年' + ccyy_time_series_record.time_series_record.def_class_code_desc + '月');
					} else {
						opt.innerHTML = setHTMLforLabel(ccyy_time_series_record.ccyy_record.def_class_code_desc + ' - ' + ccyy_time_series_record.time_series_record.def_class_code_desc);
					}					
					dc_time_category_element.appendChild(opt);
					time_category_value_counter++;
				}
			}			
			if (has_map_ccyy_time_series_map) {
				break;
			}
		}		
		// did not build time series, so year only
		if (!has_map_ccyy_time_series_map) {
			for (var ccyy_index in map_ccyy_list) {
				var ccyy_record = map_ccyy_list[ccyy_index];
				ccyy_record.ccyy_index = ccyy_index;
				time_category_value_map[time_category_value_counter] = ccyy_record;
				var opt = document.createElement('option');
				opt.value = time_category_value_counter;
				opt.innerHTML = setHTMLforLabel(ccyy_record.def_class_code_desc);
				dc_time_category_element.appendChild(opt);
				time_category_value_counter++;
			}
			time_category_value_year_only = true;
		}		
		dc_time_category_element.selectedIndex = time_category_value_counter - 1;
	}	
	setMapTimeSeriesDetail(dc_time_category_element.selectedIndex);
	cmd_mdt_deferred.resolve( all_mdt_list );
}

function setMapTimeSeriesDetail(selected_id) {
	for (var lookup_index in default_demographics_lookup_path) {
		var lookup = default_demographics_lookup_path[lookup_index];
		if (lookup.class_var == CCYY) {
			delete default_demographics_lookup_path[lookup_index];
		}
	}	
	if (time_category_value_year_only) {
		var ccyy_record = time_category_value_map[selected_id];		
		default_demographics_lookup_path.push({
			class_var: CCYY,
			class_code: ccyy_record.ccyy_index
		});
	} else {
		var ccyy_time_series_record = time_category_value_map[selected_id];		
		for (var lookup_index in default_demographics_lookup_path) {
			var lookup = default_demographics_lookup_path[lookup_index];
			if (lookup.class_var == ccyy_time_series_record.class_var) {
				delete default_demographics_lookup_path[lookup_index];
			}
		}		
		default_demographics_lookup_path.push({
			class_var: CCYY,
			class_code: ccyy_time_series_record.ccyy_index
		});
		default_demographics_lookup_path.push({
			class_var: ccyy_time_series_record.class_var,
			class_code: ccyy_time_series_record.class_code
		});
	}
	var lookup_path = [];	
	for (var lookup_index in default_demographics_lookup_path) {
		var lookup = default_demographics_lookup_path[lookup_index];
		if (lookup.class_var != 'DC') {
			lookup_path.push(lookup);
		}
	}
	var cc_id = document.getElementById("dc-category").value;
	lookup_path.push({
		class_var: 'DC',
		class_code: cc_id.toString()
	});	
	setTableLookupPath(lookup_path);
	if (vector_layer_landd_dc) {
		var source_obj = vector_layer_landd_dc.getSource();
		source_obj.changed();
	}
}

// build the classification radio button for column / row selection
function buildCvHeaderRadioButton(table_data, def_class_desc, cv_index, element, hidden_chart_cv_cc_class, id) {
	var cv_div = document.createElement('div');
	cv_div.classList.add('statistic_result_3');
	if (id) {
		cv_div.id = id;
	}
	if (hidden_chart_cv_cc_class) {
		cv_div.classList.add(hidden_chart_cv_cc_class);
	}
	if (id === "cust_tv") {
		$(element).prepend(cv_div);
	} else {
		element.appendChild(cv_div);
	}
	var subject_right_sub_title_div = document.createElement('div');
	subject_right_sub_title_div.classList.add('subject_right_sub_title');
	subject_right_sub_title_div.classList.add('margin_top_30');
	cv_div.appendChild(subject_right_sub_title_div);
	var title_h = document.createElement('div');
	title_h.classList.add('h6');
	title_h.innerHTML = setHTMLforLabel(def_class_desc, true);
	title_h.innerHTML = title_h.innerHTML + '<i aria-hidden="true" class="material-icons"><span class="dummy_collapse">' + title_h.innerHTML + ' ' + cust_text.exp_col + '</span></i>';
	title_h.setAttribute("data-target", "#cv_" + cv_index);
	title_h.setAttribute("data-toggle", "collapse");
	var title_a = document.createElement('a');
	title_a.classList.add('expand_more_less');
	title_a.innerHTML = title_h.outerHTML;
	title_a.href = "#cv_" + cv_index;
	title_a.setAttribute("data-toggle", "collapse");
	title_a.setAttribute("aria-expanded", "true");
	subject_right_sub_title_div.appendChild(title_a);	
	var detail_div = document.createElement('div');
	detail_div.classList.add('collapse');
	detail_div.classList.add('show');
	detail_div.id = 'cv_' + cv_index;
	cv_div.appendChild(detail_div);	
	var cv_body_div = document.createElement('div');
	cv_body_div.classList.add('cv_body');
	detail_div.appendChild(cv_body_div);	
	var cv_position = document.createElement('div');
	var p_h1 = document.createElement("span");
	p_h1.innerHTML = table_text.position;
	cv_position.appendChild(p_h1);	
	// radio buttons for position
	var radio_1 = buildCvRadioButton(CV + '_' + cv_index, ROW);
	var radio_2 = buildCvRadioButton(CV + '_' + cv_index, COLUMN);	
	var p_1 = document.createElement("label");
	var p_2 = document.createElement("label");	
	p_1.innerHTML = table_text.row;
	p_2.innerHTML = table_text.column;
	p_1.setAttribute('for', radio_1.id);
	p_2.setAttribute('for', radio_2.id);
	p_1.classList.add('for_checkbox');
	p_2.classList.add('for_checkbox');
	cv_position.classList.add('positions');
	cv_position.appendChild(radio_1);
	cv_position.appendChild(p_1);
	cv_position.appendChild(radio_2);
	cv_position.appendChild(p_2);
	if (id === "cust_tv") {	
		var div = $("<div />").addClass("tvSorting");
		div.html(buildTvSortingBtn(table_data));
		cv_body_div.appendChild(cv_position);
		cv_body_div.appendChild(div[0]);	
	} else {
		cv_body_div.appendChild(cv_position);
	}
	return cv_body_div;
}
function buildTvSortingBtn(table_data) {
	var check = $("<div />").addClass("cdm_checkbox");
	var radio1 = $("<input />").attr("type", "radio").attr("name", "rdoTVSorting").attr("value", "tv_asc").attr("id", "rdoTVSortingAsc").attr("aria-label", menu_text.asc);
	var radio2 = $("<input />").attr("type", "radio").attr("name", "rdoTVSorting").attr("value", "tv_desc").attr("id", "rdoTVSortingDesc").attr("aria-label", menu_text.desc);
	if (table_data.component_data.rev_chrono) {
		radio2.attr("checked", "checked");
	} else {
		radio1.attr("checked", "checked");
	}
	check.append($("<div />").append($("<span />").html(menu_text.chronological), 
		radio1, $("<label />").attr("for", "rdoTVSortingAsc").addClass("for_checkbox").html(menu_text.asc), 
		radio2, $("<label />").attr("for", "rdoTVSortingDesc").addClass("for_checkbox").html(menu_text.desc)));
	return check[0].outerHTML;
}
function checkTvSortingRadio(table_data, radio1, radio2) {
	radio1 = (radio1 || $("#rdoTVSortingAsc"))[0];
	radio2 = (radio2 || $("#rdoTVSortingDesc"))[0];
	if (radio1 && radio2) {
		if (table_data.component_data.rev_chrono) {
			radio1.checked = false;
			radio2.checked = true;
		} else {
			radio2.checked = false;
			radio1.checked = true;
		}
	}
}
/*function appendTvRadioBtnEvent() {
	$("#rdoTVSortingAsc")[0].addEventListener("change", function () {
		console.log(1);
		var data = table_data_list[table_data.table_id];
		data.component_data.rev_chrono = false;
	});
	$("#rdoTVSortingDesc")[0].addEventListener("change", function () {
		console.log(2);
		var data = table_data_list[table_data.table_id];
		data.component_data.rev_chrono = true;
	});
}*/

$(".table_chart_button_a").bind('keypress',function (event){ 
	if(event.keyCode == 13) {
		tableChartButtonAction(this);
	}
});

$('.table_chart_button_a').on('click',function(){
	tableChartButtonAction(this);
});

function tableChartButtonAction(this_obj) {
	var table_show = false;
	if ((this_obj.classList) && (this_obj.classList.contains('web_report_table_button'))) {
		table_show = true;
	}	
	var parent = this_obj.parentElement;
	for (var c_index in parent.children) {
		var child_element = parent.children[c_index];
		if ((child_element.classList) && (child_element.classList.contains('active'))) {
			child_element.classList.remove('active');
		}
	}	
	var parent_parent_element = parent.parentElement;
	for (var c_index in parent_parent_element.children) {
		var child_element = parent_parent_element.children[c_index];
		if ((child_element) && (child_element.classList)) {
			if (child_element.classList.contains('web_report_table')) {
				if (table_show) {
					child_element.style.display = 'block';
				} else {
					child_element.style.display = 'none';
				}
			}
			if (child_element.classList.contains('cnsd_chart')) {
				if (table_show) {
					child_element.style.display = 'none';
				} else {
					child_element.style.display = 'block';
				}
			}
		}
	}
	$(this_obj).addClass('active');
}

function adjustCdmButtonDiv() {
	var cdm_buttons_element = document.getElementById('cdm_buttons');
	var cdm_buttons_toggle_1_element = document.getElementById('cdm_buttons_toggle_1');
	var cdm_buttons_toggle_2_element = document.getElementById('cdm_buttons_toggle_2');
	if (cdm_buttons_element) {
		if ((window.innerWidth > 768) && (last_window_width <= 768)) {
			if (!cdm_buttons_element.classList.contains('show')) {
				cdm_buttons_element.classList.add('show');
			}
		} else if ((window.innerWidth <= 768) && (last_window_width > 768)) {
			if (cdm_buttons_element.classList.contains('show')) {
				cdm_buttons_element.classList.remove('show');
				if (cdm_buttons_toggle_1_element) {
					cdm_buttons_toggle_1_element.classList.add('collapsed');
					cdm_buttons_toggle_1_element.setAttribute('aria-expanded', 'false');
				}
				if (cdm_buttons_toggle_2_element) {
					cdm_buttons_toggle_2_element.classList.add('collapsed');
					cdm_buttons_toggle_2_element.setAttribute('aria-expanded', 'false');
				}
			}
		}
	}
	last_window_width = window.innerWidth;
}

function getUrlVarsParam(parameters) {
    var vars = {};
    var parts = ('?' + parameters).replace(/[?&]+([^=&]+)=([^&]*)/gi, function (m,key,value) {
        vars[key] = value;
    });
    return vars;
}

function buildCvRadioButton(v, row_column) {
	var radio = document.createElement("input");
	radio.id = getCvRadioButtonValueName(v, row_column);
	radio.value = getCvRadioButtonValueName(v, row_column);
	radio.type = RADIO;
	radio.name = RADIO + '_' + v;
	return radio;
}
//added 20230620
function buildRadioButton(id,value,name) {
	var radio = document.createElement("input");
	radio.id = id;
	radio.value = value;
	radio.type = RADIO;
	radio.name = name;
	return radio;
}
//
function buildSvRadioButton(v, left_right_top_bottom) {
	var radio = document.createElement("input");
	radio.id = getSvRadioButtonValueName(v, left_right_top_bottom);
	radio.value = getSvRadioButtonValueName(v, left_right_top_bottom);
	radio.type = RADIO;
	radio.name = RADIO + '_' + v;
	return radio;
}

/*	Generate an element name for a specified radio button.

v: for classification it is the field name, for statistics it is SV
row_column: ROW / COLUMN
left_right: LEFT / RIGHT (optional)
top_bottom: TOP / BOTTOM (optional)	*/
function getRadioButtonValueName(v, row_column, left_right, top_bottom) {
	var value_name = '';
	if (row_column == COLUMN) {
		value_name = value_name + '_' + COLUMN;		
		if (top_bottom == COLUMN_TOP) {
			value_name = value_name + '_' + COLUMN_TOP;
		}
		if (top_bottom == COLUMN_BOTTOM) {
			value_name = value_name + '_' + COLUMN_BOTTOM;
		}
	}
	if (row_column == ROW) {
		value_name = value_name + '_' + ROW;		
		if (left_right == ROW_LEFT) {
			value_name = value_name + '_' + ROW_LEFT;
		}
		if (left_right == ROW_RIGHT) {
			value_name = value_name + '_' + ROW_RIGHT;
		}
	}
	return RADIO + value_name + '_' + v;
}

function getCvRadioButtonValueName(v, row_column) {
	var value_name = '';
	if (row_column == COLUMN) {
		value_name = value_name + '_' + COLUMN;
	}
	if (row_column == ROW) {
		value_name = value_name + '_' + ROW;
	}
	return RADIO + value_name + '_' + v;
}

function getSvRadioButtonValueName(v, left_right_top_bottom) {
	var value_name = '';
	if (left_right_top_bottom == COLUMN_TOP) {
		value_name = value_name + '_' + COLUMN_TOP;
	}
	if (left_right_top_bottom == COLUMN_BOTTOM) {
		value_name = value_name + '_' + COLUMN_BOTTOM;
	}
	if (left_right_top_bottom == ROW_LEFT) {
		value_name = value_name + '_' + ROW_LEFT;
	}
	if (left_right_top_bottom == ROW_RIGHT) {
		value_name = value_name + '_' + ROW_RIGHT;
	}
	return RADIO + value_name + '_' + v;
}

/*	Check if the specified radio button is checked.
v: for classification it is the field name, for statistics it is SV
row_column: ROW / COLUMN
left_right: LEFT / RIGHT (optional)
top_bottom: TOP / BOTTOM (optional)	*/
function isRadioButtonSelected(v, row_column, left_right, top_bottom) {
	var radio_id = getRadioButtonValueName(v, row_column, left_right, top_bottom);
	var radio = document.getElementById(radio_id);
	return ((radio) && (radio.checked));
}

function setSvSpShowFromCheckBox(table_data) {
	var check_boxes_element = document.getElementById('statisticsCheckBoxes');
	var sv_sp_show_count = 0;
	if (check_boxes_element) {	
		// radio buttons for position
		var radio_1_id = getSvRadioButtonValueName(SV, ROW_LEFT);
		var radio_2_id = getSvRadioButtonValueName(SV, ROW_RIGHT);
		var radio_3_id = getSvRadioButtonValueName(SV, COLUMN_TOP);
		var radio_4_id = getSvRadioButtonValueName(SV, COLUMN_BOTTOM);
		var sv_radio_1 = document.getElementById(radio_1_id);
		var sv_radio_2 = document.getElementById(radio_2_id);
		var sv_radio_3 = document.getElementById(radio_3_id);
		var sv_radio_4 = document.getElementById(radio_4_id);		
		if (sv_radio_1.checked) {
			table_data.component_data.sv_position = ROW_LEFT;
			table_data.has_row = true;
		} else if (sv_radio_2.checked) {
			table_data.component_data.sv_position = ROW_RIGHT;
			table_data.has_row = true;
		} else if (sv_radio_3.checked) {
			table_data.component_data.sv_position = COLUMN_TOP;
			table_data.has_column = true;
		} else if (sv_radio_4.checked) {
			table_data.component_data.sv_position = COLUMN_BOTTOM;
			table_data.has_column = true;
		}
		for (var stat_var in table_data.lang_data.sv_list) {
			var sv_record = table_data.lang_data.sv_list[stat_var];
			var sv_index = sv_record.sv_index;			
			// sp fields
			for (var stat_pres in sv_record.sp_list) {
				var sp_record = sv_record.sp_list[stat_pres];
				var sp_index = sp_record.sp_index;
				var sv_sp_index = sv_index + '_' + sp_index;
				var sp_checkbox_id = SP + '_' + sv_sp_index;
				var sp_checkbox = document.getElementById(sp_checkbox_id);				
				sp_record.show = sp_checkbox.checked;
				if (sp_checkbox.checked) {
					sv_sp_show_count++;
				}
			}
		}		
	}
	return sv_sp_show_count;
}

// calculate the number of bits available for safe characters
function calculateSafeCharactersBits(){
	var safe_characters_length = SAFE_CHARACTERS.length;
	var log_base_2_counter = 0;
	while (safe_characters_length > 1) {
		log_base_2_counter++;
		safe_characters_length = safe_characters_length >> 1;
	}
	return log_base_2_counter;
}

function generateCurrentSelectionUrl(table_data) {
	if (table_data.lookup_path && table_data.lookup_path.length > 0) {	//for map;
		return;	
	}
	// calculate the number of bits available for safe characters
	var character_safe_bit_length = calculateSafeCharactersBits();	
	var url_parameters_map = {
		cv: {},
		sv: {},
		l: false,	// l is LATEST,
		tvrvs: table_data.component_data.rev_chrono	//tvrvs is IS_REVERSE
	};	
	var ccyy_list = [];
	var no_ccyy_tv_list = [];
	// get the latest selected time series
	var has_latest_time_series_record = false;
	var ccyy_list = objectToList(table_data.ccyy_list);
	if (!ccyy_list || ccyy_list.length <= 0) {
		ccyy_list = objectToList(table_data.ccyy_f_list);
	}
	if (ccyy_list && ccyy_list.length > 0) {
		var latest_record = ccyy_list[ccyy_list.length - 1];
		has_latest_time_series_record = table_data.lang_data.cv_list[latest_record.class_var].ccg_list[latest_record.class_code_group].cc_list[latest_record.class_code].show;
	}	
	url_parameters_map[LATEST] = has_latest_time_series_record;
	for (var class_var in table_data.component_data.table_component_ccg_list) {		
		var cv_parameter = {};		
		var comp_cv_record = table_data.component_data.table_component_ccg_list[class_var];
		var cv_index = table_data.cv_index_map[class_var];
		var cv_record = table_data.cv_map[cv_index];		
		var cv_total_show = 0;
		for (var ccg_i in comp_cv_record.ccg_list) {
			if (comp_cv_record.ccg_list[ccg_i].cv_total_show > 0) {
				cv_total_show = comp_cv_record.ccg_list[ccg_i].cv_total_show;
				break;
			}
		}
		cv_parameter[SHOW_TOTAL] = cv_total_show.toString();
		// get the position, ROW / COLUMN
		var cv_position = comp_cv_record.cv_position;
		cv_parameter[POSITION] = cv_position;		
		if ((typeof(idds) != 'undefined') && (idds)) {
			cv_parameter[DISPLAY_ORDER] = comp_cv_record.display_order;
		}		
		// get list of selected value		
		var temp_ccg_list = table_data.lang_data.cv_list[class_var].ccg_list;
		for (var ccg_index in temp_ccg_list) {
			var temp_cc_map = temp_ccg_list[ccg_index].cc_list;		
			var temp_cc_list = [];
			var cc_keys = [];
			for (var cc_index in temp_cc_map) {
				if (!temp_cc_map[cc_index].duplicated) {
					cc_keys.push(cc_index);
				}
			}
			//Yuk updated on 19/10/2021 Fixed avoid the incorrect sorting for month as string as table 29 show full series and default series
			//code reverted by dicky as it caused problem on default series function
			//Yuk updated on 27/9/2021 avoid the incorrect sorting for month as string
			//if (class_var != M3M) {
			cc_keys.sort(sortAlphaNum);
			/*}*/
			for (var cc_key in cc_keys) {
				var cc_index = cc_keys[cc_key];
				var cc_record = temp_cc_map[cc_index];
				temp_cc_list.push(cc_record);				
				if (class_var == CCYY) {
					ccyy_list.push(cc_index);
				}
			}
			var current_cv_list = "";
			var byte_value = 0;
			var bit_counter = 0;
			for (var i in temp_cc_list) {
				var cc_record = temp_cc_list[i];				
				bit_counter = i % character_safe_bit_length;
				if (bit_counter == 0) {
					// save old byte
					if (i > 0) {
						current_cv_list = SAFE_CHARACTERS[byte_value] + current_cv_list;
					}					
					byte_value = 0;
				}				
				if (cc_record.show) {
					byte_value += 1 << bit_counter;
				}
			}
			current_cv_list = SAFE_CHARACTERS[byte_value] + current_cv_list;			
			cv_parameter[ccg_index] = current_cv_list;
		}		
		url_parameters_map[CV][class_var] = cv_parameter;
	}
	// sv, sp data
	url_parameters_map[SV][POSITION] = table_data.component_data.sv_position;
	// sort the SV display order
	table_data.component_data.table_component_list.sort(compareDisplayOrder);	
	for (var sv_index in table_data.component_data.table_component_list) {
		var comp_sv_record = table_data.component_data.table_component_list[sv_index];
		var stat_var = comp_sv_record.stat_var;
		var stat_pres = comp_sv_record.stat_pres;
		if (table_data.lang_data.sv_list[stat_var].sp_list[stat_pres].show) {
			if (!url_parameters_map[SV][stat_var]) {
				url_parameters_map[SV][stat_var] = [];
			}
			url_parameters_map[SV][stat_var].push(stat_pres);
		}
	}
	var url_parameters = JSON.stringify(url_parameters_map);
	var compressed = LZString.compressToEncodedURIComponent(url_parameters);	
	var href = window.location.href;
	var parameter_index = href.indexOf('?');
	if (parameter_index >= 0) {
		href = href.substring(0, parameter_index);
	}
	var hash_index = href.indexOf('#');
	if (hash_index >= 0) {
		href = href.substring(0, hash_index);
	}
	var new_url = href + "?id=" + table_data.table_id + '&param=' + compressed;
	en_url = new_url;
	tc_url = new_url;
	sc_url = new_url;	
	var api_url = href + "?id=" + table_data.table_id + '&lang=' + langDir.replace('/', '') + '&param=' + compressed;	
	if (href.indexOf('/tc/') > 0) {
		en_url = new_url.replace('/tc/', '/en/');
		sc_url = new_url.replace('/tc/', '/sc/');
		api_url = api_url.replace('/tc/web_table.html', '/api/get.php');
	} else if (href.indexOf('/sc/') > 0) {
		tc_url = new_url.replace('/sc/', '/tc/');
		en_url = new_url.replace('/sc/', '/en/');
		api_url = api_url.replace('/en/web_table.html', '/api/get.php');
	} else if (href.indexOf('/en/') > 0) {
		tc_url = new_url.replace('/en/', '/tc/');
		sc_url = new_url.replace('/en/', '/sc/');
		api_url = api_url.replace('/en/web_table.html', '/api/get.php');
	}	
	if (typeof api_host !== 'undefined' && api_host) {
		api_url = api_url.replace(window.location.host, api_host);
	}
	if (table_data.lang == TC) {
		bookmark_url = tc_url;
	} else if (table_data.lang == SC) {
		bookmark_url = sc_url;
	} else {
		bookmark_url = en_url;
	}
	var url_element = document.getElementById("bookmark_url");
	if (url_element) {
		url_element.setAttribute("href", new_url);
		url_element.innerHTML = new_url.replace('&', '&amp;');
	}	
	var en_url_element = document.getElementById("en_url");
	if (en_url_element) {
		en_url_element.setAttribute("href", en_url);
		en_url_element.innerHTML = en_url.replace('&', '&amp;');
	}
	var english_url_element = document.getElementById("english_url");
	if (english_url_element) {
		var tmpUrl = en_url + '&' + no_popup + '=true';
		english_url_element.setAttribute("href", tmpUrl);
		english_url_element.innerHTML = tmpUrl.replace('&', '&amp;');
	}
	var tc_url_element = document.getElementById("tc_url");
	if (tc_url_element) {
		tc_url_element.setAttribute("href", tc_url);
		tc_url_element.innerHTML = tc_url.replace('&', '&amp;');
	}
	/*var api_url_element = document.getElementById("api_url");
	if (api_url_element) {
		api_url_element.setAttribute("href", api_url);
		api_url_element.innerHTML = api_url.replace(/&/g, '&amp;');
	}
	var python_element = document.getElementById("python_sample");
	if (python_element) {
		var python_string = 'import urllib.request\n';
		python_string += 'url_path = \"' + api_url.replace(/&/g, '&amp;') + '\"\n';
		python_string += 'with urllib.request.urlopen(url_path) as url:\n';
		python_string += '	s = url.read()\n';
		python_string += '	print(s)';
		python_element.innerHTML = python_string;
	}*/
	if (href.indexOf('web_table.html') >= 0) {
		var no_popup_option = '&' + no_popup + '=true';
		if ($("#default_series_button").is(":visible")) {
			no_popup_option += "&show_default_btn=true";
		}
		$(".language_icon_en").attr("onclick", `window.location.href='${en_url}${no_popup_option}'`);
		$(".language_icon_tc").attr("onclick", `window.location.href='${tc_url}${no_popup_option}'`);
		$(".language_icon_sc").attr("onclick", `window.location.href='${sc_url}${no_popup_option}'`);
	}
	return url_parameters_map;
}

function generateCurrentSelectionJson(table_data) {	
	var tv_period = getMinMaxTV(table_data);
	var parameters_map = {
		cv: {},
		sv: {},
		period: {
			start: tv_period[0].toString(),
			end: tv_period[1].toString()
		}
	};
	for (var cv in table_data.lang_data.cv_list) {
		var values = [];
		if (table_data.lang_data.cv_list[cv].is_time_series !== "1") {
			table_data.all_heads.filter(function (v) { return !v.is_sv && v.show && v.class_var === cv}).forEach(function (h) {
				if (h.class_code && !table_data.lang_data.cv_list[cv].ccg_list[h.class_code_group].cc_list[h.class_code].duplicated && !values.map(function (m) { return m.class_code; }).includes(h.class_code)) {
					values.push(h);
				}
			});
			values = values.sort(function (a, b) {
				if (a.indent < b.indent) {
					return -1;
				} else if (a.indent > b.indent) {
					return 1;
				} else {
					var aspan = a.other_span ? a.other_span : 1;
					var bspan = b.other_span ? b.other_span : 1;
					if (a.level - aspan < b.level - bspan) {
						 return -1;
					} else if (a.level - aspan > b.level - bspan) {
						return 1;
					} else {
						if (a.class_code_seq < b.class_code_seq) {
							return -1;
						} else {
							return 1;
						}
					}
				}
			});
			parameters_map[CV][cv] = values.map(function (v) { return v.class_code; });
		}
	}
	for (var sv in table_data.lang_data.sv_list) {
		for (var sp in table_data.lang_data.sv_list[sv].sp_list) {
			if (table_data.all_heads.filter(function (v) { return v.is_sv && (v.sv_show || v.sp_show) && v.stat_var === sv && v.stat_pres === sp; }).length > 0) {
				if (parameters_map[SV][sv]) {
					if (!parameters_map[SV][sv].includes(sp)) {
						parameters_map[SV][sv].push(sp);
					}
				} else {
					parameters_map[SV][sv] = [sp];
				}
			}
		}
	}
	parameters_map['id'] = table_data.table_id;
	parameters_map['lang'] = langDir.replace('/', '');	
	var has_latest_time_series_record = false;
	var ccyy_list = objectToList(table_data.ccyy_list);
	if (!ccyy_list || ccyy_list.length <= 0) {
		ccyy_list = objectToList(table_data.ccyy_f_list);
	}
	if (ccyy_list && ccyy_list.length > 0) {
		var latest_record = ccyy_list[ccyy_list.length - 1];
		has_latest_time_series_record = table_data.lang_data.cv_list[latest_record.class_var].ccg_list[latest_record.class_code_group].cc_list[latest_record.class_code].show;
		if (has_latest_time_series_record) {
			delete parameters_map.period.end;
		}
	}
	var parameters_string = JSON.stringify(parameters_map, null, 2);
	if (!window.isWebReport) {
		var compressed = LZString.compressToEncodedURIComponent(parameters_string);
		var api_url = (typeof(api_host) !== 'undefined' && api_host) ? api_host : window.location.origin + "/api/get.php?id=" + table_data.table_id + "&lang=" + langDir.replace('/', '') + "&param=" + compressed;
		var api_post = (typeof(api_host) !== 'undefined' && api_host) ? api_host : window.location.origin + "/api/post.php";
		$("#api_url").attr("href", api_url);
		$("#api_url").html(api_url.replace(/&/g, '&amp;'));
		var python_string = 'import urllib.request\n';
		python_string += 'url_path = \"' + api_url.replace(/&/g, '&amp;') + '\"\n';
		python_string += 'with urllib.request.urlopen(url_path) as url:\n';
		python_string += '	s = url.read().decode("utf8")\n';
		python_string += '	print(s)';
		$("#python_sample").html(python_string);
	}
	var api_element = document.getElementById("api_sample");
	if (api_element) {
		var jquery_string ='import requests' + '\n';
		jquery_string +='import json' + '\n';
		jquery_string +='url = \"'+ api_post +'\"' + '\n';
		jquery_string +='parameters =';
		jquery_string += parameters_string + '\n';
		jquery_string +='data = \{\'query\'\: json.dumps(parameters)\}' + '\n';
		jquery_string +='r = requests.post(url, data=data, timeout=20)' + '\n';
		jquery_string +='print(r.text)' + '\n';
		
		api_element.innerHTML = jquery_string;
	}	
	var jquery_element = document.getElementById("jquery_sample");
	if (jquery_element) {
		var api_url = window.location.href;
		var parameter_index = api_url.indexOf('?');
		if (parameter_index >= 0) {
			api_url = api_url.substring(0, parameter_index);
		}
		if (api_url.indexOf('/tc/') > 0) {
			api_url = api_url.replace('/tc/web_table.html', '/api/post.php');
		} else if (api_url.indexOf('/en/') > 0) {
			api_url = api_url.replace('/en/web_table.html', '/api/post.php');
		}	
		var jquery_string = 'var data = ';
		jquery_string +=parameters_string + ';\n';
		jquery_string += '$.post({\n'
		jquery_string += '  url: \"' + api_url + '\",\n';
		jquery_string += '  data: {query: data},\n' ;
		jquery_string += '  success: function (response){\n';
		jquery_string += '    console.log(response);\n';
		jquery_string += '  },\n';
		jquery_string += '  dataType: \"json\",\n';
																							
		jquery_string += '});\n';
		jquery_element.innerHTML = jquery_string;
	}
}

function getMinMaxTV(table_data) {
	var result = [999999, 0];
	var ccyy_result = [9999, 0];
	var useResult = false;
	var tvs = groupBy(table_data.all_heads.filter(function (v) { return !v.is_sv && v.is_tv && v.class_code && v.show; }), function (v) { return v.class_var; });
	for (var cv in table_data.lang_data.cv_list) {
		if (table_data.lang_data.cv_list[cv].is_time_series === "1") {
			var hdrs = tvs.get(cv);
			if (hdrs) {
				var max = hdrs.map(function (v) { return v.level; }).sort(function (a, b) { return a < b; })[0];
				var lst = hdrs.filter(function (v) { return v.level === max; });
				if (table_data.component_data.rev_chrono) {
					lst = lst.reverse();
				}
				if (lst.length > 0) {
					var temp = [getPeriodStartEnd(lst[0])[0], getPeriodStartEnd(lst[lst.length - 1])[1]];
					if (cv === CCYY) {
						ccyy_result[0] = Math.min(ccyy_result[0], temp[0]);
						ccyy_result[1] = Math.max(ccyy_result[1], temp[1]);
					} else {
						result[0] = Math.min(result[0], temp[0]);
							result[1] = Math.max(result[1], temp[1]);
						if (cv === CCYY_F) {
							ccyy_result[0] = Math.min(ccyy_result[0], Math.floor((temp[0] - 3) / 100));
							ccyy_result[1] = Math.max(ccyy_result[1], Math.floor((temp[1] - 4) / 100));
						} else {
							useResult = true;							
						}
					}
				}
			}
		}
	}
	if (result[1] === 0 || !useResult) {
		result = ccyy_result;
	}
	return result;
}

function selectAll(new_status, ignore_hidden) {
	checkbox_id_list.forEach(function (v) {
		var chk = $("#" + v)[0];
		if (chk) {
			var div = $(chk).closest(".cdm_checkbox")[0];
			if (chk.disabled || (div && div.style.display === "none")) {
				if (ignore_hidden) {
					chk.checked = new_status;
				}
			} else {
				chk.checked = new_status;
			}
		}
	});
	//added 20230620
	var myElem = document.getElementsByClassName('discrete_range ' + CCYY);
	if (myElem.length >0)
	{
		if (checkIsBookmark())
			toggleDiscrete_Range(1,CCYY);
		else
		{
			overrideSliderValues(CCYY);
			toggleDiscrete_Range(2,CCYY);
			
		}
	}
	var myElem = document.getElementsByClassName('discrete_range ' + CCYY_F);
	if (myElem.length >0)
	{
		if (checkIsBookmark())
			toggleDiscrete_Range(1,CCYY_F);		
		else
		{
			overrideSliderValues(CCYY_F);
			toggleDiscrete_Range(2,CCYY_F);		
			
		}
	}
	
	//
}

function selectCvAll(class_var, new_status) {
	var current_checkbox_id_list = checkbox_id_map[class_var];
	var i;
	for (i = 0; i < current_checkbox_id_list.length; i++) {
		var checkbox = document.getElementById(current_checkbox_id_list[i]);
		if (checkbox.disabled || $(checkbox).closest(".cdm_checkbox")[0].style.display === "none") {
			continue;
		}
		checkbox.checked = new_status;
	}
}

function setCcParentCheck(table_data, pac, id) {
	var record = pac.filter(function (v) { return v.id === id; })[0];
	if (record.cc_index) {
		document.getElementById(CC + "_" + record.cc_index).checked = true;	
	}
	if (record.parent_id) {
		setCcParentCheck(table_data, pac, record.parent_id);
	}	
}

function setCcParentUncheck(table_data, pac, id) {
	var record = pac.filter(function (v) { return v.id === id; })[0];
	if (record.cc_index) {
		document.getElementById(CC + "_" + record.cc_index).checked = false;
	}
	record.children.forEach(function (v) {
		setCcParentUncheck(table_data, pac, v);
	});
}

function generateSdmx() {
	if ((langDir == "tc/") || (langDir == "sc/")) {
		var dialog_data = document.getElementById('sdmx-message');
		dialog_data.title = "";
		var button_text = '';
		if (langDir == "tc/") {
			dialog_data.title = "請參考英文網站";
			button_text = '確定';
		} else if (langDir == "sc/") {
			dialog_data.title = "请参考英文网站";
			button_text = '确定';
		}		
		$( "#sdmx-message" ).dialog({
			minWidth: 800,
			position: { my: "center top", at: "center top", of: window },
			resizable: false,
			buttons: [{
				text: button_text,
				class: "buttonload",
				click: function() {
					$(this).dialog( "close" );
				}
			}]
		});	
		initCloseBtn();
		return;
	}	
	var table_id = table_id_list[0];
	var table_data = table_data_list[table_id];	
	var ref_id = table_data.sdmx_data.schema.ref_id;
	var today = new Date();	
	var structureSpecificDataString = "message:StructureSpecificData";
	var xmlDoc = null;
	try {
		xmlDoc = document.implementation.createDocument(table_data.sdmx_data.schema.xmlns__message, structureSpecificDataString);
	} catch (ex) {
		xmlDoc = new ActiveXObject("Microsoft.XMLDOM");
		xmlDoc.async="false";
		var message_element = xmlDoc.createElement(structureSpecificDataString);
		xmlDoc.appendChild(message_element);
		
		setXmlElementAttribute(xmlDoc, xmlDoc.getElementsByTagName(structureSpecificDataString)[0], "xmlns:message", table_data.sdmx_data.schema.xmlns__message);
	}	
	setXmlElementAttribute(xmlDoc, xmlDoc.getElementsByTagName(structureSpecificDataString)[0], "xsi:schemaLocation", table_data.sdmx_data.schema.xsi__schemaLocation);
	setXmlElementAttribute(xmlDoc, xmlDoc.getElementsByTagName(structureSpecificDataString)[0], "xmlns:xsi", table_data.sdmx_data.schema.xmlns__xsi);
	var href = window.location.href;
	var new_url = '';
	var parameter_index = href.indexOf('?');
	if (parameter_index >= 0) {
		href = href.substring(0, parameter_index);
		new_url = href + "?id=" + table_data.table_id;
	}
	//setXmlElementAttribute(xmlDoc, xmlDoc.getElementsByTagName(structureSpecificDataString)[0], "xmlns:" + ref_id, href.replace("web_table.html", last_bread_item.link));
	setXmlElementAttribute(xmlDoc, xmlDoc.getElementsByTagName(structureSpecificDataString)[0], "xmlns:" + ref_id, table_data.sdmx_data.schema.xmlns__theme);
	setXmlElementAttribute(xmlDoc, xmlDoc.getElementsByTagName(structureSpecificDataString)[0], "xmlns:footer", table_data.sdmx_data.schema.xmlns__footer);
	setXmlElementAttribute(xmlDoc, xmlDoc.getElementsByTagName(structureSpecificDataString)[0], "xmlns:dsd", table_data.sdmx_data.schema.xmlns__dsd);
	setXmlElementAttribute(xmlDoc, xmlDoc.getElementsByTagName(structureSpecificDataString)[0], "xmlns:common", table_data.sdmx_data.schema.xmlns__common);
	setXmlElementAttribute(xmlDoc, xmlDoc.getElementsByTagName(structureSpecificDataString)[0], "xmlns_xml", table_data.sdmx_data.schema.xmlns__xml);	
	var header_element = xmlDoc.createElement("message:Header");
	xmlDoc.getElementsByTagName(structureSpecificDataString)[0].appendChild(header_element);	
	var header_id_element = xmlDoc.createElement("message:ID");
	setXmlInnerText(header_id_element, ref_id + today.getFullYear() + (today.getMonth()+1) + today.getDate() + today.getHours() + today.getMinutes() + today.getSeconds());
	header_element.appendChild(header_id_element);	
	var header_test_element = xmlDoc.createElement("message:Test");
	setXmlInnerText(header_test_element, "false");
	header_element.appendChild(header_test_element);	
	var header_prepared_element = xmlDoc.createElement("message:Prepared");
	setXmlInnerText(header_prepared_element, getCdmDateString(today));
	header_element.appendChild(header_prepared_element);	
	var header_sender_element = xmlDoc.createElement("message:Sender");
	setXmlElementAttribute(xmlDoc, header_sender_element, "id", table_data.sdmx_data.schema.sender_id);
	var header_common_name_element = xmlDoc.createElement("common:Name");
	// set lang
	if (table_data.lang == TC) {
		setXmlElementAttribute(xmlDoc, header_common_name_element, "xml:lang", 'zh-Hant');
	} else if (table_data.lang == SC) {
		setXmlElementAttribute(xmlDoc, header_common_name_element, "xml:lang", 'zh-Hans');
	} else {
		setXmlElementAttribute(xmlDoc, header_common_name_element, "xml:lang", 'en');
	}
	setXmlInnerText(header_common_name_element, table_data.sdmx_data.schema.sender_name);	
	header_sender_element.appendChild(header_common_name_element);
	var header_contact_element = xmlDoc.createElement("message:Contact");
	var header_email_element = xmlDoc.createElement("message:Email");
	setXmlInnerText(header_email_element, table_data.sdmx_data.schema.sender_email);
	header_contact_element.appendChild(header_email_element);
	header_sender_element.appendChild(header_contact_element);	
	header_element.appendChild(header_sender_element);	
	var header_structure_element = xmlDoc.createElement("message:Structure");
	setXmlElementAttribute(xmlDoc, header_structure_element, "structureID", table_data.sdmx_data.schema.structureID);
	setXmlElementAttribute(xmlDoc, header_structure_element, "dimensionAtObservation", table_data.sdmx_data.schema.dimensionAtObservation);
	var href = window.location.href;
	var parameter_index = href.indexOf('?');
	if (parameter_index >= 0) {
		href = href.substring(0, parameter_index);
		var new_url = href + "?id=" + table_data.table_id;
		setXmlElementAttribute(xmlDoc, header_structure_element, "namespace", new_url);
	}	
	var header_common_structure_element = xmlDoc.createElement("common:Structure");
	var header_common_structure_ref_element = xmlDoc.createElement("Ref");
	setXmlElementAttribute(xmlDoc, header_common_structure_ref_element, "agencyID", table_data.sdmx_data.schema.agency_id);
	setXmlElementAttribute(xmlDoc, header_common_structure_ref_element, "id", ref_id);
	setXmlElementAttribute(xmlDoc, header_common_structure_ref_element, "version", table_data.sdmx_data.schema.ref_version);
	header_common_structure_element.appendChild(header_common_structure_ref_element);
	header_structure_element.appendChild(header_common_structure_element);
	header_element.appendChild(header_structure_element);	
	// search the table_data.sdmx_data.complexType for root complex type
	var complex_type_map = [];
	for (var complex_i in table_data.sdmx_data.complexType) {
		var complex_type_object = table_data.sdmx_data.complexType[complex_i];
		var complex_type_name = complex_type_object['name'];
		complex_type_map[complex_type_name] = complex_type_object;
	}
	for (var complex_i in table_data.sdmx_data.complexType) {
		var complex_type_object = table_data.sdmx_data.complexType[complex_i];
		var complex_type_name = complex_type_object['name'];
		for (element_i in complex_type_object.element) {
			var element_object = complex_type_object.element[element_i];
			complex_type_map[element_object.type].parent = complex_type_name;
		}
	}
	for (var complex_i in table_data.sdmx_data.complexType) {
		var complex_type_object = table_data.sdmx_data.complexType[complex_i];
		if (complex_type_object.parent == undefined) {
			
			buildSdmxDateSet(xmlDoc.getElementsByTagName(structureSpecificDataString)[0], xmlDoc, complex_type_object, table_data, complex_type_map, "message:DataSet");
			break;
		}
	}	
	var serializer = new XMLSerializer();
	var xmlString = '';
	try {
		xmlString = serializer.serializeToString(xmlDoc);
	} catch (ex) {
		xmlString = xmlDoc.xml;
	}
	xmlString = '<?xml version="1.0" encoding="utf-8"?>' + xmlString.replace("xmlns_xml", "xmlns:xml");	
	var zip = new JSZip();
	var filename_id = 'Table_' + table_id + '_SDMX';
	zip.file(filename_id + ".xsd", table_data.xsd);
	zip.file(filename_id + ".xml", xmlString);
	commonLogsReady(filename_id);
	zip.generateAsync({type:"blob"}).then(function (blob) { // 1) generate the zip file
        saveAs(blob, filename_id + ".zip");                          // 2) trigger the download
		//closeWindowAfterDownload();
    }, function (err) {
        console.log(err);
    });
}

function showApiPopup() {
	var dialog_data = document.getElementById('api-message');
	dialog_data.title = "API";
	if (langDir == "tc/") {
		dialog_data.title = "應用程式介面";
	} else if (langDir == "sc/") {
		dialog_data.title = "应用程式介面";
	}
	$("#api-message").dialog({
		minWidth: 800,
		resizable: false
	});
	$("#api-message").parent().css("position", "fixed");
	$("#api-message").parent().css("top", "0");
	$("#api-message").css("height", (window.innerHeight - 52) + "px", "important");
	initCloseBtn();
}

function showBookmarkPopup() {
	var dialog_data = document.getElementById('bookmark-message');
	dialog_data.title = "Bookmark";
	if (langDir == "tc/") {
		dialog_data.title = "書籤";
	} else if (langDir == "sc/") {
		dialog_data.title = "书签";
	}	
	$("#bookmark-message").dialog({
		minWidth: 800,
		position: { my: "center top", at: "center top", of: window },
		resizable: false
	});
	$("#bookmark-message").parent().css("position", "fixed");
	$("#bookmark-message").parent().css("top", "0");
	initCloseBtn();
}

function createDataDictionaryCell(row, column_counter, html_text) {
	var cell = row.insertCell(column_counter);
	cell.className = 'dictcol';
	$(cell).html(html_text);
	return cell;
}

function generateDataDictionary(table_data) {
	var data_dictionary_id = document.getElementById('data_dictionary_id');
	if (data_dictionary_id) {
		data_dictionary_id.innerHTML = table_data.table_id;
	}
	var data_dictionary_table = document.getElementById('data_dictionary');
	if (data_dictionary_table) {		
		// delete original data
		for (var i = data_dictionary_table.getElementsByTagName("tr").length; i >= 5; i--){
			data_dictionary_table.deleteRow(i - 1);
		}		
		var row_counter = 4;		
		// add sv data
		var sv_row = data_dictionary_table.insertRow(row_counter);
		createDataDictionaryCell(sv_row, 0, 'sv');
		createDataDictionaryCell(sv_row, 1, dictionary.sv);
		createDataDictionaryCell(sv_row, 2, dictionary.mandatory);
		var sv_html = '';
		for (var stat_var in table_data.lang_data.sv_list) {
			var sv_record = table_data.lang_data.sv_list[stat_var];
			sv_html = sv_html + setHTMLforLabel(stat_var + ' : ' + sv_record.def_stat_desc);
		}
		createDataDictionaryCell(sv_row, 3, sv_html);
		createDataDictionaryCell(sv_row, 4, dictionary.sv_remark);
		row_counter++;		
		// add sp data
		var sp_row = data_dictionary_table.insertRow(row_counter);
		createDataDictionaryCell(sp_row, 0, 'sp');
		createDataDictionaryCell(sp_row, 1, dictionary.sp);
		createDataDictionaryCell(sp_row, 2, dictionary.mandatory);	
		var sp_html = '';
		for (var stat_var in table_data.lang_data.sv_list) {
			var sv_record = table_data.lang_data.sv_list[stat_var];
			for (var stat_pres in sv_record.sp_list) {
				var sp_record = sv_record.sp_list[stat_pres];
				sp_html = sp_html + setHTMLforLabel(stat_pres + ' : ' + stat_var + ' - ' + sp_record.def_stat_pres_desc);
			}
		}
		createDataDictionaryCell(sp_row, 3, sp_html);
		createDataDictionaryCell(sp_row, 4, dictionary.sp_remark);
		row_counter++;		
		// add cv and cc (non time series data)
		for (var class_var in table_data.lang_data.cv_list) {			
			var cv_record = table_data.lang_data.cv_list[class_var];			
			// skip time series, the parameter is set in Period
			if (cv_record.is_time_series == '1') {
				continue;
			}			
			var cc_html = '';
			var temp_ccg_list = cv_record.ccg_list;			
			var cc_used = [];
			for (var ccg_index in temp_ccg_list) {
				var temp_ccg_record = temp_ccg_list[ccg_index];
				var temp_cc_list = temp_ccg_record.cc_list;				
				for (var class_code in temp_cc_list) {
					var cc_record = temp_cc_list[class_code];
					if (cc_record.has_data && cc_used.indexOf(class_code) < 0 && !cc_record.duplicated) {
						cc_used.push(class_code);
						var html_desc = cc_record.def_class_code_desc;
						if (cc_record.csv_tabular_class_code_desc) {
							html_desc = cc_record.csv_tabular_class_code_desc;
						}
						cc_html = cc_html + setHTMLforLabel(class_code + ' : ' + html_desc);
					}
				}
			}			
			var cv_row = data_dictionary_table.insertRow(row_counter);
			createDataDictionaryCell(cv_row, 0, class_var);
			createDataDictionaryCell(cv_row, 1, setHTMLforLabel(cv_record.def_class_desc));
			createDataDictionaryCell(cv_row, 2, dictionary.optional);
			createDataDictionaryCell(cv_row, 3, cc_html);
			createDataDictionaryCell(cv_row, 4, '');
			row_counter++;
		}
	}
}

function getGeneralCC(class_var, mdt_lookup_path, table_data) {
	for (var i in mdt_lookup_path) {
		var lookup_record = mdt_lookup_path[i];
		if (class_var == lookup_record.class_var) {
			var ccg_list = table_data.lang_data.cv_list[class_var].ccg_list;
			var class_code = lookup_record.class_code;
			for (var ccg_index in ccg_list) {
				var ccg_record = ccg_list[ccg_index];
				if (ccg_record.cc_list[class_code]) {
					return ccg_record.cc_list[class_code];
				}
			}
		}
	}
	return null;
}

function showTooltips(results) {
	var scodes = [];
	results.forEach(function (v) {
		if (v) {
			v.subject_code_list.forEach(function (sc) {
				if (!$.grep(scodes, function (f) { return f.subject === sc.subject; })[0]) {
					scodes.push(clone(sc));
				}
			});
		}
	});
	preload_glossary_data(scodes).done(
		function() {
			if (!tooltipsLoaded) {
				try {
					if (typeof default_demographics_lookup_path === 'undefined') {
						applyKeyword();
					} else {
						var lst = [];
						table_id_list.forEach(function (v) {
							lst.push("#" + v);
							lst.push("#" + v + "_table_notes_table_notes");
							lst.push("#" + v + "_table_header_notes_table_notes");
							lst.push("#" + v + "_table_source");
						});
						applyKeyword(null, null, lst);
					}
					tooltipsLoaded = true;
				} catch(err) {
					// ignore
				}
			}
			results.forEach(function (v) {
				if (v && v.table_data) {
					var tid = v.table_data.table_id;
					hideLoadingById('t', tid);
				} else {
					try {
						applyKeyword();
						hideLoadingById('t');
					} catch(err) { }
				}
			});
		}
	);
}

function loadGlossaryInMap(table_data) {
	if (typeof default_demographics_lookup_path !== 'undefined') {	//map page
		var scodes = getSubjectCodes(table_data);
		preload_glossary_data(scodes).done(
			function() {
				try {
					applyKeyword("#" + table_data.table_id, scodes);
					applyKeyword("#" + table_data.table_id + "_table_notes_table_notes", scodes);
					applyKeyword("#" + table_data.table_id + "_table_header_notes_table_notes", scodes);
					//applyKeyword("#" + table_data.table_id + "_table_sd_notes_table_notes", scodes);
					applyKeyword("#" + table_data.table_id + "_table_source", scodes);
				} catch(err) {
					// ignore
				}
			}
		);
	}
}