var parseindex = 0;

function generateDownload(type, original_table_id_list, no_sd_value) {
	buildMultipleTables(type, original_table_id_list, no_sd_value);	
}

function closeWindowAfterDownload() {
	if (close_download) {
		sleep(0).then(function () {
			window.close();
		});
	}
}

function buildCsvCellData(cols, i, j, csv_row) {
	var result = [];
	// Clean innertext to remove multiple spaces and jumpline (break csv)
	var data = cols[j].innerText.replace(/(\r\n|\n|\r)/gm, '').replace(/(\s\s)/gm, ' ');
	var current_class_name = cols[j].className.split(" ");
	var is_ccyy = cols[j].getAttribute('data-CCYY');
	var col_count = cols[j].colSpan;
	var row_count = cols[j].rowSpan;	
	var row_position = 0;
	for (var c_counter = 0; c_counter < col_count; c_counter++) {
		for (var r_counter = 0; r_counter < row_count; r_counter++) {
			// Push escaped string
			var temp_row = csv_row[i + r_counter];				
			if ((c_counter == 0) && (r_counter == 0)) {
				row_position = temp_row.length;
				// check and see if there is any gap in the row
				for (var row_i = 0; row_i < temp_row.length; row_i++) {
					if (temp_row[row_i] == undefined) {
						row_position = row_i;
						break;
					}
				}
			}				
			var insert_data = '';
			if (((r_counter == 0) && ((current_class_name.includes('titlecol')) || (current_class_name.includes('titletotalcol')) || (current_class_name.includes('titlesvcol')))) ||
				((c_counter == 0) && (current_class_name.includes('titlerow')) || (current_class_name.includes('pac_titlerow')) || (current_class_name.includes('titletotalrow')) || (current_class_name.includes('titlesvrow'))) ||
				((r_counter == 0) && (c_counter == 0) && ((current_class_name.includes('titlecvcol')) || (current_class_name.includes('titlecvrow')))) ||
				(current_class_name.includes('pac_titlecvrow')) ||
				(current_class_name.includes('pac_titlecvcol')) ||
				(current_class_name.includes('data')) ||
				(current_class_name.includes('datatotal')) ||
				(current_class_name.length === 0)) {
				insert_data = data;
			} else if (c_counter === 0 && current_class_name.includes("hiddentdforExport")) {
				insert_data = data;
			}
			temp_row[row_position + c_counter] = insert_data;				
		}
	}
	no_ccyy_tv.forEach(function (t) {
		var row_column = cols[j].getAttribute('data-' + t);
		if (row_column) {
			if (row_column === 'row') {
				result.push({ row: i + 1, column: -1 });
			} else if (row_column === 'column') {
				result.push({ row: -1, column: j + 1 });
			}
		}
	});
	return result;
}

function generateCsvNote(csv_array, table_id, no_sd_value) {
	var has_note = table_data_list[table_id].notes_data_export.length > 0;
	var notes_array_simple = [];
	if (has_note) {
		csv_array.push([table_text.notes]);
		createNotesArray(table_data_list[table_id].notes_data_export, notes_array_simple, csv_array, no_sd_value);	
		csv_array.push(['']);
	}
	var notes = table_data_list[table_id].source_data.filter(function (v) { 
		if (Array.isArray(v)) {
			return v.length > 0;
		} else {
			return v;
		}
	});
	if (notes && notes.length > 0) {
		csv_array.push([table_text.source]);	
		createNotesArray(notes, notes_array_simple, csv_array, no_sd_value);
	}
	if (no_sd_value) {
		csv_array.push(['']);
		csv_array.push([down_text.csv.remark]);
		csv_array.push([down_text.csv.remark2]);
	}
}

function generatesDownloads(type, original_table_id_list, no_sd_value) {
	var original_table_show = $('.table_show').css( "display" );
	$(".table_show").show();	
	var download_table_id_list = [];
	var web_report_table_seq = [];
	for (var table_index in original_table_id_list) {
		var table_id = original_table_id_list[table_index];		
		switch (table_id) {
			case 'M04':
				var selected_district = getSelectedDistrictString();
				var selected_ccyy = getGeneralCC(CCYY, default_demographics_lookup_path, table_data_list[table_id]);
				var selected_mm = getGeneralCC(MM, default_demographics_lookup_path, table_data_list[table_id]);				
				var table_title = '';
				if (langDir == "tc/") {
					table_title = selected_ccyy.def_class_code_desc + '年' + selected_mm.def_class_code_desc + '月' + selected_district + '按行業主類劃分的機構單位數目';
				} else if (langDir == "sc/") {
					table_title = selected_ccyy.def_class_code_desc + '年' + selected_mm.def_class_code_desc + '月' + selected_district + '按行业主类划分的机构单位数目';
				} else {
					table_title = 'Number of Establishments in ' + selected_district + ' Analysed by Industry Section, ' + selected_mm.def_class_code_desc + ' ' + selected_ccyy.def_class_code_desc;
				}
				var header_cell_1 = document.getElementById(table_id + TABLE_HEADER_CELL_ID_1);
				header_cell_1.setAttribute('data-t', 's');
				header_cell_1.innerHTML = "<strong>" + table_title + "</strong>";
				download_table_id_list.push(table_id);
				break;
			case 'M03':
				var selected_district = getSelectedDistrictString();
				var selected_ccyy = getGeneralCC(CCYY, default_demographics_lookup_path, table_data_list[table_id]);
				var selected_mm = getGeneralCC(MM, default_demographics_lookup_path, table_data_list[table_id]);
				
				var table_title = '';
				if (langDir == "tc/") {
					table_title = selected_ccyy.def_class_code_desc + '年' + selected_mm.def_class_code_desc + '月' + selected_district + '按行業主類及性別劃分的從業人數';
				} else if (langDir == "sc/") {
					table_title = selected_ccyy.def_class_code_desc + '年' + selected_mm.def_class_code_desc + '月' + selected_district + '按行业主类及性别划分的从业人数';
				} else {
					table_title = 'Number of Persons Engaged in ' + selected_district + ' Analysed by Industry Section and Sex, ' + selected_mm.def_class_code_desc + ' ' + selected_ccyy.def_class_code_desc;
				}				
				var header_cell_1 = document.getElementById(table_id + TABLE_HEADER_CELL_ID_1);
				header_cell_1.setAttribute('data-t', 's');
				header_cell_1.innerHTML = "<strong>" + table_title + "</strong>";
				download_table_id_list.push(table_id);
				break;
			case 'M05':
			case 'M06':
				break;
			default:
				download_table_id_list.push(table_id);
				if (window.isWebReport) {
					var seq = $("#table_name_" + table_id).closest(".tab-content").data("seq");
					web_report_table_seq.push(seq);
				} else {
					
				}
				break;			
		}
	}
	var table_id_string = (window.isWebReport ? web_report_table_seq.join(' ') : download_table_id_list.join(' '));
	var extra_name = '';
	if (no_sd_value) {
		extra_name = ' (excl symbols)';
	}
	if (type == 'csv_tabular') {
		extra_name = ' (tabular)';
		if (window.isWebReport && original_table_id_list.length > 1) {
			buildCsvTabular(web_element.eCode + extra_name + "_" + getSiteLang()+ ".zip", download_table_id_list, no_sd_value);
		} else {
			buildCsvTabular("Table " + table_id_string + extra_name + "_" + getSiteLang()+ ".zip", download_table_id_list, no_sd_value);
		}
	} 
	else if (type == 'csv') {
		if (window.isWebReport && original_table_id_list.length > 1) {
			buildCsv(web_element.eCode + extra_name + (download_table_id_list.length > 1 ?  "_" + getSiteLang()+ ".zip" :  "_" + getSiteLang()+ ".csv"), download_table_id_list, no_sd_value);
		} else {
			buildCsv("Table " + table_id_string + extra_name + (download_table_id_list.length > 1 ? "_" + getSiteLang()+ ".zip" : "_" + getSiteLang()+ ".csv"), download_table_id_list, no_sd_value);
		}
	} else if (type === "Excel") {
		if (window.isWebReport && original_table_id_list.length > 1) {
			buildExcel(web_element.eCode + extra_name + "_" + getSiteLang()+ ".xlsx", table_id_string, download_table_id_list, no_sd_value);
		} else {
			buildExcel("Table " + table_id_string + extra_name + "_" + getSiteLang()+ ".xlsx", table_id_string, download_table_id_list, no_sd_value);
		}
	}
	if (original_table_show == 'none') {
		$(".table_show").hide();
	}
	if (window.isWebReport) {
		removePageLoading();
	}
}

function buildCsvTabular(filename, download_table_id_list, no_sd_value) {
	var zip = new JSZip();
	// build mdt
	for (var table_index in download_table_id_list) {
		var table_id = download_table_id_list[table_index];
		var ws_name = "Table " + table_id;
		var meta_filename = "Table_meta " + table_id;
		var seq = "";
		if (window.isWebReport) {
			seq = $("#table_name_" + table_id).closest(".tab-content").data("seq");
			ws_name = "Table " + seq;
			meta_filename = "Table_meta " + seq;
		}
		// get all cv
		var csv_header_map = [];
		var csv_header_row = ['STAT_VAR', 'STAT_PRES'];
		csv_header_map['mdt_sv_index'] = 0;
		csv_header_map['mdt_sp_index'] = 1;
		var column_counter = 2;		
		// sort the CV display order
		var cv_order_list = [];
		var table_lang_data = table_data_list[table_id].lang_data_exp;
		for (var cv in table_lang_data.cv_list) {
			var itm = table_lang_data.cv_list[cv];
			itm.class_var = cv;
			cv_order_list.push(itm);
		}
		cv_order_list.sort(compareDisplayOrder);
		var csv_array = [];
		for (var class_var_index in cv_order_list){
			var cv_record = cv_order_list[class_var_index];
			var class_var = cv_record.class_var;
			csv_header_row.push(class_var);
			csv_header_map[class_var] = column_counter;
			column_counter++;
		}
		csv_header_row.push('OBS_VALUE');
		csv_header_map['obs_value'] = column_counter;
		column_counter++;
		csv_header_row.push('SD_VALUE');
		csv_header_map['sd_value'] = column_counter;
		column_counter++;
		csv_array.push(csv_header_row);
		var meta_csv_array = [];
		var sd_used_list = [];
		var tbl = $("#" + table_id)[0] || $("#" + DEFAULT_TABLE)[0];
		for (var mdt_i = 1; mdt_i <= mdt_counter[table_id]; mdt_i++) {
			var mdt_record = mdt_counter_map[table_id][mdt_i];
			if (mdt_record) {				
				var csv_row = [];
				var sd_value_array = mdt_record.sd_value.split(',');
				sd_value_array = sd_value_array.filter(Boolean);
				var obs_value_suppressed = false;
				var symbol_suppressed = false;
				if (sd_value_array.length > 0) {
					for (var sd_value_index in sd_value_array) {
						var sd_value = sd_value_array[sd_value_index];
						if (all_sd_list[sd_value].obs_value_suppressed == '1') {
							obs_value_suppressed = true;
						}
						if (all_sd_list[sd_value].symbol_suppressed == '1') {
							symbol_suppressed = true;
						}
						if (sd_used_list.indexOf(sd_value) < 0) {
							sd_used_list.push(sd_value);
						}
					}
				}				
				for (var mdt_column in mdt_record) {
					if (csv_header_map[mdt_column] !== undefined) {
						if ((mdt_column == 'obs_value') && (obs_value_suppressed)){
							csv_row[csv_header_map[mdt_column]] = '';
						} else if ((mdt_column == 'sd_value') && (symbol_suppressed)) {
							csv_row[csv_header_map[mdt_column]] = '';
						} else if (mdt_column == 'obs_value') {
							csv_row[csv_header_map[mdt_column]] = mdt_record.mdt_obs_value_no_sd_text;
						} else {
							csv_row[csv_header_map[mdt_column]] = mdt_record[mdt_column];
						}
					}
				}				
				csv_array.push(csv_row);
			}
		}
		meta_csv_array.push([]);		
		var table_title_string = ds_title.table + (window.isWebReport ? seq : table_id) + ds_title.symbol + table_data_list[table_id].lang_data.tb_title;
		
		meta_csv_array.push([table_title_string]);
		meta_csv_array.push([]);
		meta_csv_array.push(down_text.tabular.header_row_1);
		meta_csv_array.push(down_text.tabular.header_row_2);
		meta_csv_array.push(down_text.tabular.header_row_3);
		meta_csv_array.push(down_text.tabular.header_row_4);
		meta_csv_array.push(down_text.tabular.header_row_5);
		meta_csv_array.push(down_text.tabular.header_row_6);
		meta_csv_array.push(down_text.tabular.header_row_7);
		meta_csv_array.push(down_text.tabular.header_row_8);
		meta_csv_array.push(down_text.tabular.header_row_9);
		meta_csv_array.push(down_text.tabular.header_row_10);
		meta_csv_array.push([]);
		meta_csv_array.push(down_text.tabular.sv_row_1);
		meta_csv_array.push(down_text.tabular.sv_row_2);
		for (var stat_var in table_data_list[table_id].lang_data.sv_list) {
			var sv_record = table_data_list[table_id].lang_data.sv_list[stat_var];
			var meta_array = [stat_var, sv_record.def_stat_desc];
			meta_array = addNoteText(meta_array, sv_record);
			meta_csv_array.push(meta_array);
		}
		meta_csv_array.push([]);
		meta_csv_array.push(down_text.tabular.sp_row_1);
		meta_csv_array.push(down_text.tabular.sp_row_2);
		for (var stat_var in table_data_list[table_id].lang_data.sv_list) {
			var sv_record = table_data_list[table_id].lang_data.sv_list[stat_var];
			for (var stat_pres in sv_record.sp_list) {
				var sp_record = sv_record.sp_list[stat_pres];
				var meta_array = [stat_var, stat_pres, sp_record.def_stat_pres_desc];
				meta_array = addNoteText(meta_array, sp_record);
				meta_csv_array.push(meta_array);
			}
		}
		meta_csv_array.push([]);
		meta_csv_array.push(down_text.tabular.cv_row_1);
		meta_csv_array.push(down_text.tabular.cv_row_2);
		for (var class_var_index in cv_order_list){
			var cv_record = cv_order_list[class_var_index];
			var class_var = cv_record.class_var;
			var meta_array = [class_var, cv_record.def_class_desc];
			meta_array = addNoteText(meta_array, cv_record);
			meta_csv_array.push(meta_array);
		}		
		meta_csv_array.push([]);
		meta_csv_array.push(down_text.tabular.cc_row_1);
		meta_csv_array.push(down_text.tabular.cc_row_2);
		var check_cc_list = [];
		for (var class_var_index in cv_order_list){
			var cv_record = cv_order_list[class_var_index];
			var class_var = cv_record.class_var;
			for (var ccg_index in cv_record.ccg_list) {
				var ccg_record = cv_record.ccg_list[ccg_index];
				for (var class_code in ccg_record.cc_list) {
					var cc_record = ccg_record.cc_list[class_code];
					var curr_def_class_code_desc = cc_record.def_class_code_desc;
					if (cc_record.csv_tabular_class_code_desc) {
						curr_def_class_code_desc = cc_record.csv_tabular_class_code_desc;
					}
					var meta_array = [class_var, class_code, curr_def_class_code_desc];
					//var cc_index = getCCIndex(table_data_list, table_id, class_var, ccg_index, class_code);
					//if (cc_index && check_cc_list.indexOf(cc_index) < 0) {
					if (check_cc_list.indexOf(class_code) < 0) {
						meta_array = addNoteText(meta_array, cc_record);
						meta_csv_array.push(meta_array);
						check_cc_list.push(class_code);
					}
				}
			}
		}		
		meta_csv_array.push([]);
		meta_csv_array.push(down_text.tabular.sd_row_1);
		meta_csv_array.push(down_text.tabular.sd_row_2);
		for (var sd_index in sd_used_list) {
			var sd_value = sd_used_list[sd_index];
			if (sd_value) {
				meta_csv_array.push([sd_value, all_sd_list[sd_value].sd_desc]);
			}
		}		
		meta_csv_array.push([]);
		meta_csv_array.push(down_text.tabular.ccg_row_1);
		meta_csv_array.push(down_text.tabular.ccg_row_2);
		for (var class_var_index in cv_order_list){
			var cv_record = cv_order_list[class_var_index];
			var class_var = cv_record.class_var;
			for (var ccg_index in cv_record.ccg_list) {
				var ccg_record = cv_record.ccg_list[ccg_index];
				for (var class_code in ccg_record.cc_list) {
					var cc_record = ccg_record.cc_list[class_code];
					meta_csv_array.push([class_var, ccg_index, class_code]);
				}
			}
		}
		meta_csv_array.push([]);
		meta_csv_array.push(down_text.tabular.pac_row_1);
		meta_csv_array.push(down_text.tabular.pac_row_2);
		for (var class_var_index in cv_order_list){
			var cv_record = cv_order_list[class_var_index];
			var class_var = cv_record.class_var;
			for (var pac_index in cv_record.pac_list) {
				var pac_record = cv_record.pac_list[pac_index];
				meta_csv_array.push([class_var, pac_record.parent_class_code_group, pac_record.parent_class_code, pac_record.child_class_code_group, pac_record.child_class_code]);
			}
		}
		meta_csv_array.push([]);
		meta_csv_array.push(down_text.tabular.note_row_1);
		meta_csv_array.push(down_text.tabular.note_row_2);		
		var div = document.createElement("div");
		div.innerHTML = table_data_list[table_id].lang_data.tb_fn;
		var note_text = div.textContent || div.innerText || "";
		note_text = note_text.trim();
		meta_csv_array.push([note_text]);
		var worksheet_1 = XLSX.utils.aoa_to_sheet(csv_array);
		var worksheet_2 = XLSX.utils.aoa_to_sheet(meta_csv_array);
		/* add worksheet to workbook */		
		var wb = XLSX.utils.book_new();
		if (ws_name.length > 31) {
			ws_name = ws_name.substr(0, 31);
		}
		XLSX.utils.book_append_sheet(wb, worksheet_2, ws_name);
		var csv_data = XLSX.utils.sheet_to_csv(worksheet_1);		
		/* bookType can be any supported output type */
		var wopts = { bookType:'csv', bookSST:false, type:'array' };
		var wbout = XLSX.write(wb,wopts);	
		zip.file(ws_name + ".csv", csv_data);
		zip.file(meta_filename + ".csv", wbout, {binary: true});		
	}	
	zip.generateAsync({type:"blob"}).then(function (blob) { // 1) generate the zip file
		saveAs(blob, filename);                          // 2) trigger the download
		//closeWindowAfterDownload();
	}, function (err) {
		errorLog("CsvTabular", "zip file", err);
	});
}

function getCCIndex(table_data_list, table_id, class_var, ccg_index, class_code) {
	var result = null;
	var cv = table_data_list[table_id].lang_data.cv_list[class_var];
	if (cv) {
		var ccg = cv.ccg_list[ccg_index];
		if (ccg) {
			var cc = ccg.cc_list[class_code];
			if (cc) {
				result = cc.cc_index;
			}
		}
	}
	if (!result) {
		console.log(class_code);
	}
	return result;
}

function buildCsv(filename, download_table_id_list, no_sd_value) {
	var zip = new JSZip();
	for (var table_index in download_table_id_list) {
		var table_id = download_table_id_list[table_index];
		var ws_name = "Table " + table_id;
		if (window.isWebReport) {
			var seq = $("#table_name_" + table_id).closest(".tab-content").data("seq");
			ws_name = "Table " + seq;
		}
		// Sheet names cannot exceed 31 chars
		if (ws_name.length > 31) {
			ws_name = ws_name.substr(0, 31);
		}
		var tbl = $("#" + table_id)[0] || $("#" + DEFAULT_TABLE)[0];
		var csv_array = [];
		$(tbl).find(".hiddentrforExport").show();
		var sd_value_prev_tr = null;
		var sd_value_tr = "";
		if (!no_sd_value) {
			sd_value_prev_tr = $($(tbl).find(".exclude_sd_values")[0]).prev();
			if (sd_value_prev_tr[0]) {
				while (sd_value_prev_tr[0].classList.contains("pseudotr")) {
					sd_value_prev_tr = $(sd_value_prev_tr).prev();
				}
			}
			$(tbl).find(".exclude_sd_values").toArray().forEach(function (v) {
				sd_value_tr += v.outerHTML;
			});
			$(tbl).find(".exclude_sd_values").remove();
		}
		// for idds, remove button in cv cell
		var cv_row_cell_list = [];
		var cv_col_cell_list = [];
		if ((typeof(idds) != 'undefined') && (idds) && (typeof(IDDS_CV_POPUP_CODE) != 'undefined')) {
			cv_row_cell_list = getElementsByClassName(document.body, 'titlecvrow');
			cv_col_cell_list = getElementsByClassName(document.body, 'titlecvcol');
			
			for (var cell_i in cv_row_cell_list) {
				var cv_cell = cv_row_cell_list[cell_i];
				cv_cell.innerHTML = cv_cell.getAttribute('data-text_only');
			}
			for (var cell_i in cv_col_cell_list) {
				var cv_cell = cv_col_cell_list[cell_i];
				cv_cell.innerHTML = cv_cell.getAttribute('data-text_only');
			}
		}		
		$(tbl).find("th").toArray().forEach(function (v) {
			var text = $(v).data("excel_text");
			if (text) {
				$(v).html(text);
			}
		});
		$(tbl).find(".pseudotd").remove();
		$(tbl).find(".pseudotr").remove();
		$(tbl).find(".data").toArray().concat($(tbl).find(".datatotal").toArray()).forEach(function (v) {
			$(v).html($(v).data((no_sd_value ? "mdt_obs_value_no_sd_text" : "mdt_obs_value_sd_text")));
		});
		var rows = tbl.rows;	// Select rows from table_id
		var csv = [];	// Construct csv
		var csv_row = [];
		for (var i = 0; i < rows.length; i++) {
			csv_row[i] = [];
		}
		var nonEmptyCellIndex = [];
		var addedFlag = false;
		for (var i = 0; i < rows.length; i++) {
			var cols = rows[i].querySelectorAll('td, th');
			for (var j = 0; j < cols.length; j++) {					
				buildCsvCellData(cols, i, j, csv_row);
				for (var k = 0; k < csv_row[i].length; k++) {
					if (!addedFlag) {
						if (csv_row[i][k]) {
							nonEmptyCellIndex.push(k);
						} else {
							nonEmptyCellIndex.push(-1);
						}
					} else if (csv_row[i][k] && csv_row[i][k].trim() && nonEmptyCellIndex[k] > -1) {
						nonEmptyCellIndex[k] = -1;
					}
				}
				if (!addedFlag && nonEmptyCellIndex.length > 0) {
					addedFlag = true;
				}
			}
			if (cols && cols.length > 0) {	//no_ccyy_tv is placed in column area
				var row = csv_row[i];
				csv.push(row.join(','));
				csv_array.push(row);
			}
		}
		nonEmptyCellIndex.filter(function (v) { return v > -1; }).reverse().forEach(function (idx) {
			csv_array.forEach(function (v) {
				v.splice(idx, 1);
			});
		});
		$(tbl).find(".data").toArray().concat($(tbl).find(".datatotal").toArray()).forEach(function (v) {
			var text = $(v).data("original_value");
			if (text) {
				$(v).html(text);
			}
		});
		if (sd_value_prev_tr && sd_value_tr) {
			sd_value_prev_tr[0].outerHTML += sd_value_tr;
		}
		$("#" + table_id).find("th").toArray().concat($("#" + DEFAULT_TABLE).find("th").toArray()).forEach(function (v) {
			var text = $(v).data("html_text");
			if (text) {
				$(v).html(text);
			}
		});	
		$(tbl).find(".hiddentrforExport").hide();
		// for idds, add back cv button
		if ((typeof(idds) != 'undefined') && (idds) && (typeof(IDDS_CV_POPUP_CODE) != 'undefined')) {			
			for (var cell_i in cv_row_cell_list) {
				var cv_cell = cv_row_cell_list[cell_i];
				cv_cell.innerHTML = cv_cell.innerHTML + IDDS_CV_POPUP_CODE;
			}
			for (var cell_i in cv_col_cell_list) {
				var cv_cell = cv_col_cell_list[cell_i];
				cv_cell.innerHTML = cv_cell.innerHTML + IDDS_CV_POPUP_CODE;
			}
		}		
		/*csv_array.push(['']);
		generateCsvNote(csv_array, table_id, no_sd_value);
		var last_revision_date_element = document.getElementById("last_revision_date");
		if (last_revision_date_element) {
			var release_date_output = last_revision_date_element.innerHTML;			
			csv_array.push(['']);
			csv_array.push([date_time_string.release_date + release_date_output]);
		}
		var csv_string = csv.join('\n');*/
		var worksheet = XLSX.utils.aoa_to_sheet(csv_array);
		var wb = XLSX.utils.book_new();
		XLSX.utils.book_append_sheet(wb, worksheet, ws_name);
		var wopts = { bookType:'csv', bookSST:false, type:'array' };
		var wbout = XLSX.write(wb, wopts);
		if (download_table_id_list.length > 1) {
			zip.file(ws_name + ".csv", wbout, {binary: true});
		}
		addPseudoCellsforPAC(tbl);
	}
	if (download_table_id_list.length > 1) {
		zip.generateAsync({type: "blob"}).then(function (blob) {
			saveAs(blob, filename);
			//closeWindowAfterDownload();
		}, function (err) {
			errorLog("Csv", "zip file", err);
		});
	} else {
		XLSX.writeFile(wb, filename, {cellStyles: true, bookSST: true}); /* write workbook */	
		//closeWindowAfterDownload();
	}
	if ($("#" + table_id)[0]) {
		applyKeyword("#" + table_id);
	} else {
		applyKeyword("#" + DEFAULT_TABLE);
	}
}

function buildExcel(filename, table_id_string, download_table_id_list, no_sd_value) {
	var tbls1 = $(".tab-content > .container:not(.active)");
	var tbls2 = $(".subject_right_title_pub_detail:not(.show)");
	if (download_table_id_list.length > 1 || (download_table_id_list.length > 0 && $(tbls1).find("#" + download_table_id_list[0])[0])) {
		tbls1.addClass("active");
	} else {
		tbls1 = [];
	}
	if (download_table_id_list.length > 1 || (download_table_id_list.length > 0 && $(tbls2).find("#" + download_table_id_list[0])[0])) {
		tbls2.addClass("show");
	} else {
		tbls2 = [];
	}
	var wb = XLSX.utils.book_new();
	for (var table_index in download_table_id_list) {
		var collapses = [];
		var start_row = 0;
		var worksheet = null;
		var table_id = download_table_id_list[table_index];
		var ws_name = "Table " + table_id;
		var child = $("#" + table_id)[0];
		do {
			var div = $(child).closest(".collapse:not(.show)")[0];
			if (div) {
				child = div;
				$(div).addClass("show");
				collapses.push(div);
			} else {
				child = null;
			}
		} while (child);
		if (window.isWebReport) {
			var seq = $("#table_name_" + table_id).closest(".tab-content").data("seq");
			ws_name = "Table " + seq;
		}
		// for idds, remove button in cv cell
		var cv_row_cell_list = [];
		var cv_col_cell_list = [];
		if ((typeof(idds) != 'undefined') && (idds) && (typeof(IDDS_CV_POPUP_CODE) != 'undefined')) {
			cv_row_cell_list = getElementsByClassName(document.body, 'titlecvrow');
			cv_col_cell_list = getElementsByClassName(document.body, 'titlecvcol');
			
			for (var cell_i in cv_row_cell_list) {
				var cv_cell = cv_row_cell_list[cell_i];
				cv_cell.innerHTML = cv_cell.getAttribute('data-text_only');
			}
			for (var cell_i in cv_col_cell_list) {
				var cv_cell = cv_col_cell_list[cell_i];
				cv_cell.innerHTML = cv_cell.getAttribute('data-text_only');
			}
		}
		var tbl = $("#" + table_id)[0] || $("#" + DEFAULT_TABLE)[0];
		$(tbl).find(".hiddentrforExport").show();
		var sd_value_prev_tr = null;
		var sd_value_tr = "";
		if (!no_sd_value) {
			sd_value_prev_tr = $($(tbl).find(".exclude_sd_values")[0]).prev();
			if (sd_value_prev_tr[0]) {
				while (sd_value_prev_tr[0].classList.contains("pseudotr")) {
					sd_value_prev_tr = $(sd_value_prev_tr).prev();
				}
			}
			$(tbl).find(".exclude_sd_values").toArray().forEach(function (v) {
				sd_value_tr += v.outerHTML;
			});
			$(tbl).find(".exclude_sd_values").remove();
		}
		$(tbl).find("th").toArray().concat($(tbl).find(".pseudoth").toArray()).forEach(function (v) {
			var text = $(v).data("excel_text");
			if (text) {
				$(v).css("fontSize", "15px");
				$(v).html(text);
			}
		});
		// Sheet names cannot exceed 31 chars
		if (ws_name.length > 31) {
			ws_name = ws_name.substr(0, 31);
		}
		if (no_sd_value) {
			$(tbl).find(".data").toArray().concat($(tbl).find(".datatotal").toArray()).forEach(function (v) {
				var txt = $(v).data("no_sd");
				$(v).html(txt);
				v.setAttribute("data-v", txt);	//$(v).data("v", txt) does not work
				v.setAttribute("data-t", "n");
			});
		} else {
			$(tbl).find(".data").toArray().concat($(tbl).find(".datatotal").toArray()).forEach(function (v) {
				var sd_flg = $(v).data("has_sd_text");
				if (sd_flg) {
					$(v).html($(v).data("obs_value_numeric_sd"));
					v.setAttribute("data-t", "s");
				} else {
					$(v).html($(v).data("no_sd"));
					v.setAttribute("data-t", "n");
				}
				v.setAttribute("data-v", $(v).html());
			});
		}
		var startCell = "A1";
		$(tbl).find(".pseudotd").remove();
		$(tbl).find(".pseudotr").remove();
		worksheet = XLSX.utils.table_to_sheet(tbl, { borders: true });
		var rows = tbl.getElementsByTagName("tr").length;
		start_row += rows;
		var columnCount = XLSX.utils.decode_range(worksheet['!ref']).e.c + 1;
		var max_column_alpha = numToAlpha(columnCount - 1);
		var max_cell = max_column_alpha + rows;
		XLSX.utils.sheet_set_range_style(worksheet, "A1:" + max_cell, {alignment: { wrapText: true }});
		XLSX.utils.sheet_set_range_style(worksheet, "A1:" + max_cell, { sz: 11.5, name: 'Arial' });
		XLSX.utils.sheet_set_range_style(worksheet, startCell, {alignment: { horizontal: "left", wrapText: false }});
		$(tbl).find(".data").toArray().concat($(tbl).find(".datatotal").toArray()).forEach(function (v) {
			var text = $(v).data("original_value");
			if (text) {
				$(v).html(text);
			}
		});
		if (sd_value_prev_tr && sd_value_tr) {
			sd_value_prev_tr[0].outerHTML += sd_value_tr;
		}
		$(tbl).find("th").toArray().concat($(tbl).find(".pseudoth").toArray()).forEach(function (v) {
			var text = $(v).data("html_text");
			if (text) {
				$(v).html(text);
			}
			$(v).css("fontSize", "");
		});
		$(tbl).find(".hiddentrforExport").hide();
		// for idds, add back cv button
		if ((typeof(idds) != 'undefined') && (idds) && (typeof(IDDS_CV_POPUP_CODE) != 'undefined')) {
			for (var cell_i in cv_row_cell_list) {
				var cv_cell = cv_row_cell_list[cell_i];
				cv_cell.innerHTML = cv_cell.innerHTML + IDDS_CV_POPUP_CODE;
			}
			for (var cell_i in cv_col_cell_list) {
				var cv_cell = cv_col_cell_list[cell_i];
				cv_cell.innerHTML = cv_cell.innerHTML + IDDS_CV_POPUP_CODE;
			}
		}
		XLSX.utils.book_append_sheet(wb, worksheet, ws_name);	/* add worksheet to workbook */
		if (collapses.length > 0) {
			collapses.forEach(function (v) {
				$(v).removeClass("show");
			});
		}
		addPseudoCellsforPAC(tbl);
	}
	XLSX.writeFile(wb, filename, {cellStyles: true, bookSST: true}); /* write workbook */
	//closeWindowAfterDownload();
	$(tbls1).removeClass("active");
	$(tbls2).removeClass("show");
	if ($("#" + table_id)[0]) {
		applyKeyword("#" + table_id);
	} else {
		applyKeyword("#" + DEFAULT_TABLE);
	}
}

function create_gap_rows(ws, nrows) {
	var ref = XLSX.utils.decode_range(ws["!ref"]);       // get original range
	ref.e.r += nrows;                                    // add to ending row
	ws["!ref"] = XLSX.utils.encode_range(ref);           // reassign row
}

function setXmlElementAttribute(xmlDoc, xml_element, attribute_name, attribute_value) {
	var attribute = xmlDoc.createAttribute(attribute_name);
	if (attribute_value) {
		attribute.nodeValue = attribute_value;
	} else {
		attribute.nodeValue = '';
	}
	xml_element.setAttributeNode(attribute);
}

/* function buildSdmxTVAttribute(xmlDoc, xml_element, complex_type, table_data, cv_lookup_list, ccyyObject,timeSeriesObject) {
 
	for (var attribute_i in complex_type.attribute) {
		var attribute_object = complex_type.attribute[attribute_i];		
		var attribute_value = attribute_object.default_value;		
		if (attribute_object.code_list['id']) {
			attribute_value = attribute_object.code_list['id'];
		}		
				
			for (var cv_index in cv_lookup_list) {
				var class_var = cv_lookup_list[cv_index];			
				for (var index in attribute_object.cv) {
					var attribute_object_detail = attribute_object.cv[index];
					if (attribute_object_detail.class_var == class_var) {					
						if (attribute_object_detail.default_value) {
							
							attribute_value = replaceVar(attribute_object_detail.default_value,table_data, cv_lookup_list, cv_cc_lookup_list, sv_lookup, sp_lookup, mdt_record,ccyyObject,timeSeriesObject);
						}
						if (attribute_object_detail.show_code == 1) {
							attribute_value = class_var;
						}
						if (attribute_object_detail.show_desc == 1) {
							attribute_value = table_data.lang_data.cv_list[class_var].def_class_code_desc;
						}
						if (attribute_object_detail.value) {
							attribute_value = replaceVar(attribute_object_detail.value,table_data, cv_lookup_list, cv_cc_lookup_list, sv_lookup, sp_lookup, mdt_record,ccyyObject,timeSeriesObject);
						}
					}
				}
			}		
			
			 for (var index in attribute_object.cc) {
				var attribute_object_detail = attribute_object.cc[index];
				var temp_class_code;
				if (timeSeriesObject)
					temp_class_code = timeSeriesObject.time_series_record.class_code;
				else
					temp_class_code = ccyyObject.def_class_code_desc;
				
				if (attribute_object_detail.class_code == temp_class_code) {					
					if (attribute_object_detail.default_value) {
						attribute_value = replaceVar(attribute_object_detail.default_value,ccyyObject,timeSeriesObject);
					}
					if (attribute_object_detail.show_code == 1) {
						attribute_value = temp_class_code;
					}
					
					if (attribute_object_detail.value) {
						attribute_value = replaceVar(attribute_object_detail.default_value,ccyyObject,timeSeriesObject);
					}
				}
			}		 
		//console.log('run buildSdmxTVAttribute');
		setXmlElementAttribute(xmlDoc, xml_element, attribute_object.name, attribute_value);
	}
}
 */

function buildSdmxAttribute(xmlDoc, xml_element, complex_type, table_data, cv_lookup_list, cv_cc_lookup_list, sv_lookup, sp_lookup, mdt_record,ccyyObject,timeSeriesObject) {
  
	for (var attribute_i in complex_type.attribute) {
		var attribute_object = complex_type.attribute[attribute_i];		
		var attribute_value = attribute_object.default_value;		
		if (attribute_object.code_list['id']) {
			attribute_value = attribute_object.code_list['id'];
		}		
		for (var index in attribute_object.sv) {
			var attribute_object_detail = attribute_object.sv[index];
			if (attribute_object_detail.stat_var == sv_lookup) {				
				if (attribute_object_detail.default_value) {
					attribute_value = replaceVar(attribute_object_detail.default_value,table_data, null, null, table_data.lang_data.sv_list[sv_lookup], null, mdt_record,ccyyObject,timeSeriesObject);
				}
				if (attribute_object_detail.show_code == 1) {
					attribute_value = sv_lookup;
				}
				if (attribute_object_detail.show_desc == 1) {
					attribute_value = table_data.lang_data.sv_list[sv_lookup].def_stat_desc;
				}
				if (attribute_object_detail.value) {
					attribute_value = attribute_object_detail.value;
				}
			}
		}		
		for (var index in attribute_object.sp) {
			var attribute_object_detail = attribute_object.sp[index];
			if (attribute_object_detail.stat_pres == sp_lookup && attribute_object_detail.stat_var == sv_lookup) {				
				var sp_object = table_data.lang_data.sv_list[sv_lookup].sp_list[sp_lookup];
				if (attribute_object_detail.default_value) {
					attribute_value = replaceVar(attribute_object_detail.default_value,table_data, null, null, table_data.lang_data.sv_list[sv_lookup], sp_object, mdt_record,ccyyObject,timeSeriesObject);
				}
				if (attribute_object_detail.show_code == 1) {
					attribute_value = sp_lookup;
				}
				if (attribute_object_detail.show_desc == 1) {
					attribute_value = sp_object.def_stat_pres_desc;
				}
				if (attribute_object_detail.show_stat_type == 1) {
					attribute_value = sp_object.def_stat_type;
				}
				if (attribute_object_detail.show_unit == 1) {
					attribute_value = sp_object.def_unit;
				}
				if (attribute_object_detail.show_unit_desc == 1) {
					attribute_value = sp_object.def_unit_desc;
				}
				if (attribute_object_detail.show_decmials == 1) {
					attribute_value = sp_object.def_decimals;
				}
				if (attribute_object_detail.show_unit_mult == 1) {
					attribute_value = sp_object.def_unit_mult;
				}
				if (attribute_object_detail.value) {
					attribute_value = replaceVar(attribute_object_detail.value,table_data, null, null, null, sp_object, mdt_record,ccyyObject,timeSeriesObject);
				}
			}
		}		
		for (var cv_index in cv_lookup_list) {
			var class_var = cv_lookup_list[cv_index];			
			for (var index in attribute_object.cv) {
				var attribute_object_detail = attribute_object.cv[index];
				if (attribute_object_detail.class_var == class_var) {					
					if (attribute_object_detail.default_value) {												
						attribute_value = replaceVar(attribute_object_detail.default_value,table_data, table_data.lang_data.cv_list[class_var], null, table_data.lang_data.sv_list[sv_lookup], table_data.lang_data.sv_list[sv_lookup].sp_list[sp_lookup], mdt_record,ccyyObject,timeSeriesObject);						
					}
					if (attribute_object_detail.show_code == 1) {
						attribute_value = class_var;
					}
					if (attribute_object_detail.show_desc == 1) {
						attribute_value = table_data.lang_data.cv_list[class_var].def_class_code_desc;
					}
					if (attribute_object_detail.value) {
						
						attribute_value = replaceVar(attribute_object_detail.value,table_data, table_data.lang_data.cv_list[class_var], null, table_data.lang_data.sv_list[sv_lookup], table_data.lang_data.sv_list[sv_lookup].sp_list[sp_lookup], mdt_record,ccyyObject,timeSeriesObject);						
												
					}
				}
			}
		}		
			
		
		for (var cv_index in cv_cc_lookup_list) {
			var cv_cc_object = cv_cc_lookup_list[cv_index];			
			for (var index in attribute_object.cc) {
				var attribute_object_detail = attribute_object.cc[index];
				if (attribute_object_detail.class_code == cv_cc_object.class_code) {					
					if (attribute_object_detail.default_value) {
						//attribute_value = attribute_object_detail.default_value;
						attribute_value = replaceVar(attribute_object_detail.default_value,table_data, table_data.lang_data.cv_list[class_var], cv_cc_object, table_data.lang_data.sv_list[sv_lookup], table_data.lang_data.sv_list[sv_lookup].sp_list[sp_lookup], mdt_record,ccyyObject,timeSeriesObject);						
					}
					if (attribute_object_detail.show_code == 1) {
						attribute_value = cv_cc_object.class_code;
					}
					if ((attribute_object_detail.show_desc == 1) && (cv_cc_object.cc_object)) {
						if (cv_cc_object.cc_object.xml_class_code_desc) {
							attribute_value = cv_cc_object.cc_object.xml_class_code_desc;
						} else {
							attribute_value = removeHtmlCode(cv_cc_object.cc_object.def_class_code_desc);
						}
					}
					if (attribute_object_detail.value) {
						attribute_value = replaceVar(attribute_object_detail.value,table_data, table_data.lang_data.cv_list[class_var], cv_cc_object, table_data.lang_data.sv_list[sv_lookup], table_data.lang_data.sv_list[sv_lookup].sp_list[sp_lookup], mdt_record,ccyyObject,timeSeriesObject);						
					}
				}
			}
		}		
		for (var tb_i in attribute_object.tb) {
			var tb_object = attribute_object.tb[tb_i];
			if (tb_object.tb_code == table_data.table_id) {				
				if (tb_object.default_value) {
					attribute_value = tb_object.default_value;
				}
				if (tb_object.show_code == 1) {
					attribute_value = tb_object.tb_code;
				}
				if (tb_object.show_desc == 1) {
					attribute_value = table_data.lang_data.tb_title;
				}
				if (tb_object.show_fn == 1) {
					attribute_value = removeHtmlCode(table_data.lang_data.tb_fn);
				}
				if (tb_object.value) {
					attribute_value = tb_object.value;
				}
			}
		}
		//--- do pure time series related mapping ---
		if (ccyyObject || timeSeriesObject)
		{
		 for (var index in attribute_object.cc) {
				var attribute_object_detail = attribute_object.cc[index];
				var temp_class_code;
				
				if (timeSeriesObject)
				
					temp_class_code = timeSeriesObject.time_series_record.class_code;				
				
				else
					temp_class_code = ccyyObject.def_class_code_desc;
				
				if (attribute_object_detail.class_code == temp_class_code) {					
					if (attribute_object_detail.default_value) {
						attribute_value = replaceVar(attribute_object_detail.default_value,table_data, cv_lookup_list, cv_cc_lookup_list, sv_lookup, sp_lookup, mdt_record,ccyyObject,timeSeriesObject);
					}
					if (attribute_object_detail.show_code == 1) {
						attribute_value = temp_class_code;
					}
					
					if (attribute_object_detail.value) {
						attribute_value = replaceVar(attribute_object_detail.value,table_data, cv_lookup_list, cv_cc_lookup_list, sv_lookup, sp_lookup, mdt_record,ccyyObject,timeSeriesObject);
					}
				}
			}		 
		}
		
		if (mdt_record) {			
			var suppressed = false;
			var sd_text = '';
			var sd_values = mdt_record['sd_value'];
			var sd_value_array = sd_values.split(',');
			for (var sd_value_index in sd_value_array) {
				var sd_value = sd_value_array[sd_value_index];
				var sd_record = table_data.sd_list[sd_value];
				if (sd_record) {
					if (sd_record.obs_value_suppressed == '1') {
						suppressed = true;
					}					
					for (var index in attribute_object.sd) {
						var attribute_object_detail = attribute_object.sd[index];
						if (attribute_object_detail.sd_symbol == sd_record.sd_symbol) {							
							if (attribute_object_detail.default_value) {
								attribute_value = attribute_object_detail.default_value;
							}
							if (attribute_object_detail.show_code == 1) {
								attribute_value = sd_record.sd_symbol;
							}
							if (attribute_object_detail.show_desc == 1) {
								attribute_value = sd_record.sd_desc;
							}
							if (attribute_object_detail.value) {
								attribute_value = attribute_object_detail.value;
							}
														
							
						}
					}
				}
			}
		}
		//console.log('run buildSdmxAttribute');
		setXmlElementAttribute(xmlDoc, xml_element, attribute_object.name, attribute_value);
		
	}
}

function buildSdmxDateSet(parent_element, xmlDoc, data_set_complex_type, table_data, complex_type_map, node_name) {	
	var ref_id = table_data.sdmx_data.schema.ref_id;	
	var data_set_element = xmlDoc.createElement(node_name);	
	setXmlElementAttribute(xmlDoc, data_set_element, "xsi:type", ref_id + ':' +  data_set_complex_type.name);
	setXmlElementAttribute(xmlDoc, data_set_element, "dsd:structureRef", table_data.sdmx_data.schema.structureID);
	setXmlElementAttribute(xmlDoc, data_set_element, "dsd:dataScope", 'DataStructure');	
	buildSdmxAttribute(xmlDoc, data_set_element, data_set_complex_type, table_data, [], [], null, null, null);	
	for (element_i in data_set_complex_type.element) 
	{
	var element_object = data_set_complex_type.element[element_i];
	var series_complex_type = complex_type_map[element_object.type];		
	// create all different sv, sp, cv, cc combination		
		for (var stat_var in table_data.lang_data.sv_list) {
			var stat_var_object = table_data.lang_data.sv_list[stat_var];			
			if (stat_var_object.show) {
				for (var stat_pres in stat_var_object.sp_list) {
					var stat_pres_object = stat_var_object.sp_list[stat_pres];					
					if (stat_pres_object.show) {						
						var sdmx_cv_list = [];
						var sdmx_cv_cc_list = [];						
						for (var class_var in table_data.component_data.table_component_ccg_list) {
							var cv_data = table_data.component_data.table_component_ccg_list[class_var];
							var class_var_object = table_data.lang_data.cv_list[class_var];							
							if (class_var_object.is_time_series != "1") {
								sdmx_cv_list.push(class_var);							
							
								var sdmx_cc_list = [];
								var sdmx_cv_cc_object_list = [];
								var has_total = 0;
								for (var ccg_i in cv_data.ccg_list) {
									var ccg_data = cv_data.ccg_list[ccg_i];
									var ccg_object = class_var_object.ccg_list[ccg_data.class_code_group];									
									for (var class_code in ccg_object.cc_list) {
										var cc_object = ccg_object.cc_list[class_code];
										if (cc_object.show) {
											if (sdmx_cc_list.indexOf(class_code) < 0) {
												sdmx_cc_list.push(class_code);
												sdmx_cv_cc_object_list.push({
													class_var: class_var,
													class_code: class_code,
													cc_object: cc_object
												});
											}
										}
									}								
									if (ccg_data.show_total == ccg_data.cv_total_show && ccg_data.cv_total_show > 0) {
										 has_total = ccg_data.cv_total_show;
									}									
								}								
								if (has_total > 0 && (sdmx_cc_list.indexOf("") < 0)) {
									var itm = {
										class_var: class_var,
										class_code: "",
										cc_object: null
									}
									if (has_total === 1) {
										sdmx_cc_list.push("");
										sdmx_cv_cc_object_list.push(itm);
									} else if (has_total === 2) {
										sdmx_cc_list.splice(0, 0, "");
										sdmx_cv_cc_object_list.splice(0, 0, itm);
									}
								}							
								sdmx_cv_cc_list.push(sdmx_cv_cc_object_list);
							}
						
						}						
						// Generating combinations from n arrays with m elements
						if (sdmx_cv_cc_list.length == 0)
						{
							var cv_cc_list = [];
							buildSdmxSeries(data_set_element, xmlDoc, series_complex_type, table_data, complex_type_map, ref_id + ":" + element_object.name, sdmx_cv_list, cv_cc_list, stat_var, stat_pres);
						}
						else
						{
							var permutate_cv_cc_list = cartesian(sdmx_cv_cc_list);		
							
							for (var t_i in permutate_cv_cc_list) {
								var cv_cc_list = permutate_cv_cc_list[t_i];
								buildSdmxSeries(data_set_element, xmlDoc, series_complex_type, table_data, complex_type_map, ref_id + ":" + element_object.name, sdmx_cv_list, cv_cc_list, stat_var, stat_pres);
							}
						}
					}
				}
			}
		}		
	}	
	parent_element.appendChild(data_set_element);
}

function buildSdmxSeries(parent_element, xmlDoc, series_complex_type, table_data, complex_type_map, node_name, sdmx_cv_list, cv_cc_list, stat_var, stat_pres) {
	var mdt_data = table_data.mdt_data[stat_var][stat_pres];	
	// filter mdt
	var cv_used = [];
	var count_obs = 0;
	for (c_index in cv_cc_list) {
		var cv_cc_object = cv_cc_list[c_index];
		if (cv_cc_object.class_code) {
			mdt_data = $.grep(mdt_data, function (obj) { return (obj[cv_cc_object.class_var] == cv_cc_object.class_code); });
		} else {
			// for total, may not have mdt attribute
			mdt_data = $.grep(mdt_data, function (obj) { return (obj[cv_cc_object.class_var] == '') || (!obj[cv_cc_object.class_var]); });
		}
		cv_used.push(cv_cc_object.class_var);
	}	
	if (mdt_data.length == 0) {
		return;
	}
	
	var hasShown_freq = false;
		
	var ref_id = table_data.sdmx_data.schema.ref_id;
		
	for (element_i in series_complex_type.element) {
		var element_object = series_complex_type.element[element_i];
		var obs_complex_type = complex_type_map[element_object.type];	
		// loop CCYY
		if (table_data.lang_data.cv_list[CCYY]) {						
			for (var ccg_i in table_data.lang_data.cv_list[CCYY].ccg_list) {
				var ccg_object = table_data.lang_data.cv_list[CCYY].ccg_list[ccg_i];
				for (var class_var in ccg_object.cc_list) {
					var cc_object = ccg_object.cc_list[class_var];
					if (cc_object.show) {
						if (hasShown_freq==false)
						{							
							var series_element = xmlDoc.createElement(node_name );		
							parent_element.appendChild(series_element);	
							
							if (sdmx_cv_list.includes(CCYY)==false)
								sdmx_cv_list.push(CCYY);
							
							buildSdmxAttribute(xmlDoc, series_element, series_complex_type, table_data, sdmx_cv_list, cv_cc_list, stat_var, stat_pres, null);	
							//var sdmx_tv_cv_list = [];
							sdmx_cv_list = sdmx_cv_list.filter(item => item!== CCYY);
							//sdmx_tv_cv_list.push(CCYY);
							//buildSdmxTVAttribute(xmlDoc, series_element, series_complex_type, table_data, sdmx_tv_cv_list, cv_cc_list, null);	
							//sdmx_tv_cv_list = [];
																					
							hasShown_freq = true;
						}						
						cc_object.class_var = class_var;
					if (buildSdmxObs(series_element, xmlDoc, obs_complex_type, table_data, complex_type_map, ref_id + ":" + element_object.name, sdmx_cv_list, cv_cc_list, stat_var, stat_pres, cc_object, null, mdt_data, cv_used))
					    count_obs = count_obs + 1;         	
					}
				}
			}
		}	
		
		// delete series if no obs values 
		if (count_obs == 0 && hasShown_freq == true)
		{
			if (parent_element!=null && series_element != null)
				parent_element.removeChild(series_element);
		}		
		count_obs = 0 ;
		
		// loop other time series
		if (table_data.time_series_counter > 1) {
			for (var class_var in table_data.ccyy_time_series_list) {
				if (class_var !== CCYY) {
					hasShown_freq = false;	
					
					var time_series_list = table_data.ccyy_time_series_list[class_var];
					if (class_var == 'M3M')
					{
						var m3m_series_list = table_data.ccyy_time_series_map[class_var];
						for (var t_index in m3m_series_list) {
							var time_series  = m3m_series_list[t_index];
							for (var m_index in time_series ) {
								var m_time_series = time_series[m_index];
								if (m_time_series.show)	
								{
									if (hasShown_freq==false)
									{
										//var series_element = xmlDoc.createElement(node_name + '_' + FreqValue);		
										var series_element = xmlDoc.createElement(node_name );		
										parent_element.appendChild(series_element);	
										if (sdmx_cv_list.includes(class_var)==false)
											sdmx_cv_list.push(class_var);
										buildSdmxAttribute(xmlDoc, series_element, series_complex_type, table_data, sdmx_cv_list, cv_cc_list, stat_var, stat_pres, null);	
										//var sdmx_tv_cv_list = [];
										sdmx_cv_list = sdmx_cv_list.filter(item => item!== class_var);
										//sdmx_tv_cv_list.push(class_var);
										//buildSdmxTVAttribute(xmlDoc, series_element, series_complex_type, table_data, sdmx_tv_cv_list, cv_cc_list, null);	
										//sdmx_tv_cv_list = [];						
										hasShown_freq=true;
									}						
									
									m_time_series.class_var = class_var;
								if	(buildSdmxObs(series_element, xmlDoc, obs_complex_type, table_data, complex_type_map, ref_id + ":" + element_object.name, sdmx_cv_list, cv_cc_list, stat_var, stat_pres, null, m_time_series, mdt_data, cv_used))
									count_obs = count_obs + 1;
								}
							}
						}							
					}
					else
					{		
						for (var t_index in time_series_list) {
							var time_series = time_series_list[t_index];
							if (time_series.show) {
								if (hasShown_freq==false)
								{
									//var series_element = xmlDoc.createElement(node_name + '_' + FreqValue);		
									var series_element = xmlDoc.createElement(node_name );		
									parent_element.appendChild(series_element);	
									if (sdmx_cv_list.includes(class_var)==false)
										sdmx_cv_list.push(class_var);
									buildSdmxAttribute(xmlDoc, series_element, series_complex_type, table_data, sdmx_cv_list, cv_cc_list, stat_var, stat_pres, null);	
									//var sdmx_tv_cv_list = [];
									sdmx_cv_list = sdmx_cv_list.filter(item => item!== class_var);
									//buildSdmxTVAttribute(xmlDoc, series_element, series_complex_type, table_data, sdmx_tv_cv_list, cv_cc_list, null);	
									//sdmx_tv_cv_list = [];																			
									hasShown_freq=true;
								}						
								
								time_series.class_var = class_var;
							if	(buildSdmxObs(series_element, xmlDoc, obs_complex_type, table_data, complex_type_map, ref_id + ":" + element_object.name, sdmx_cv_list, cv_cc_list, stat_var, stat_pres, null, time_series, mdt_data, cv_used))
								count_obs = count_obs + 1;
							}
						}
					}
					if (count_obs ==0 && hasShown_freq ==true)
					{
						if (parent_element!=null && series_element != null)
							parent_element.removeChild(series_element);
					}
					
				}
			}
		}
	}
}

function tokenize(expression) {
  const tokens = expression.match(/['()"']|\b\w+\b|[<>]=?|[!=]=|\|\||&&|\S/g);
  return tokens;
}

function parseCondifExpression(expression) {
  const tokens = tokenize(expression);
	parseindex= 0; 
  function parseCondifExpression() {
   
   let left = parseTerm();
    while (tokens[parseindex] === '||' || tokens[parseindex] === '&&') {
      const operator = tokens[parseindex++];
      const right = parseTerm();
      left = evaluateExpression(left, operator, right);
    }
    return left;
  }

  function parseTerm() {
    let left = parseFactor();
    while (
      tokens[parseindex] === '==' ||
      tokens[parseindex] === '!=' ||
      tokens[parseindex] === '<' ||
      tokens[parseindex] === '>' ||
      tokens[parseindex] === '<=' ||
      tokens[parseindex] === '>='
    ) {
      const operator = tokens[parseindex++];
      const right = parseFactor();
      left = evaluateExpression(left, operator, right);
    }
    return left;
  }

  function parseFactor() {
    if (tokens[parseindex] === '(') {
      parseindex++;
      const result = parseCondifExpression();
      if (tokens[parseindex] !== ')') {
        throw new Error('Mismatched parenthesis');
      }
      parseindex++;
      return result;
    } 
	
	  else {
      // Handle literal values (e.g., true, false, numbers, strings)
      const token = tokens[parseindex++];
      return parseLiteral(token, tokens);
    }
  }

  return parseCondifExpression();
}
function evaluateExpression(left, operator, right) {
  if (typeof left === 'string' || typeof right === 'string') {
    switch (operator) {
      case '==':
        return String(left) === String(right);
      case '!=':
        return String(left) !== String(right);
      default:
        throw new Error('Invalid operator for string comparison: ' + operator);
    }
  } else {
    switch (operator) {
      case '==':
        return left === right;
      case '!=':
        return left !== right;
      case '<':
        return left < right;
      case '>':
        return left > right;
      case '<=':
        return left <= right;
      case '>=':
        return left >= right;
      case '||':
        return left || right;
      case '&&':
        return left && right;
      default:
        throw new Error('Invalid operator: ' + operator);
    }
  }
}
function parseLiteral(token, tokens) {
  if (token === 'true') {
    return true;
  } else if (token === 'false') {
    return false;
  } else if (!isNaN(parseFloat(token))) {
    return parseFloat(token);
  } else if (token.match(/^['"].*['"]$/)) {
    return token.slice(1, -1);
  } else if (token.match(/^['"].*$/)) {
    // Handle string literals with whitespace
    let stringLiteral = token.slice(1);
    let nextToken = tokens[parseindex];
    while (nextToken && !nextToken.match(/.*["']$/)) {
      stringLiteral += ' ' + nextToken;
      parseindex++;
      nextToken = tokens[parseindex];
    }
    stringLiteral += ' ' + nextToken.slice(0, -1);
    parseindex++;
    return stringLiteral;
  } else {
    throw new Error('Invalid literal: ' + token);
  }
}

function condif(expression, truePartResult, falsePartResult) {
  const result = parseCondifExpression(expression);

  if (result) {
    return truePartResult;
  } else {
    return falsePartResult;
  }
}

function getFootNote(level,isConcat,separator,table_data,cur_sv,cur_sp,cur_cv,cur_cc) {
	let strLevel = 'SV';
	let blnIsConcat = true;
	let strSeparator = ':';
		
	// Validating level parameter
  const validLevels = ['SV', 'SP', 'CV', 'CC'];
  const validatedLevel = level.toUpperCase(); // Convert to uppercase for case-insensitive comparison

  if (validLevels.includes(validatedLevel)) {
    strLevel = level;
  }

  // Validating isConcat parameter
  if (typeof isConcat == 'boolean') {
    blnIsConcat = isConcat;
  }

  // Validating separator parameter
  if (typeof separator !== 'string' || separator.length !== 1 || /[<>"]|\\/.test(separator)) {
    
  }
   else
   {
	   strSeparator = separator;
   }	   

   if (strLevel.toUpperCase()=='SV')
       return loopFootNote(cur_sv,blnIsConcat,strSeparator);	
   else if   (strLevel.toUpperCase()=='SP')
		return loopFootNote(cur_sp,blnIsConcat,strSeparator);	
   else if   (strLevel.toUpperCase()=='CV')
		return loopFootNote(cur_cv,blnIsConcat,strSeparator);	
    else if   (strLevel.toUpperCase()=='CC')
		return loopFootNote(cur_cc,blnIsConcat,strSeparator);	
	else
		return '';	
   }

function loopFootNote(objLevel,isConcat,separator)
{
	let strtemp ='';
		
	if (objLevel)
	{
		if (objLevel.hasOwnProperty('note1'))
		{
			for (let i = 1;i<6;i++) {
				const propertyName =  `note${i}`;
				if (isConcat)
				{
					if (objLevel[propertyName]!='')
						strtemp += objLevel[propertyName] + separator;	
				}
				else
				{
					if (strtemp =='')
						strtemp = objLevel[propertyName];
				}
			}				
			
			if (isConcat && strtemp !='')
					strtemp = strtemp.slice(0,-1);
			
			return strtemp;
		}	
		else
		{
			// may be cc object 
			if (objLevel.hasOwnProperty('cc_object'))
			{
				if (objLevel.cc_object.hasOwnProperty('note1'))
				{
					for (let i = 1;i<6;i++) {
						const propertyName =  `note${i}`;
						if (isConcat)
						{
							if (objLevel.cc_object[propertyName]!='')
								strtemp += objLevel.cc_object[propertyName] + separator;	
						}
						else
						{
							if (strtemp =='')
								strtemp = objLevel.cc_object[propertyName];
						}
					}				
					if (isConcat && strtemp !='')
						strtemp = strtemp.slice(0,-1);
					return strtemp;
				}	
			}
			else
				return '';
			
		}		
	}	
	else
		return '';
	
	
}

function parseExpression(expression,table_data,cur_sv,cur_sp,cur_cv,cur_cc,mdt_record) {
  const padStartRegex = /padStart\((.+?)\)/gi;
  const formatM3MRegex = /formatM3M\((.+?)\)/gi;
  const condifRegex = /condif\((.+?)\)/gi;
  //const condifRegex = /condif\((.*?),(\.*?),(\.*?)\)/g;
  const footNoteRegex = /getFootNote\((.+?)\)/gi;
  
  var matches = expression.match(padStartRegex);

  if (matches) {
    matches.forEach((match) => {
      const [, args] = match.split('(');
      const [string, maxLength, fillString = ' '] = args.split(',').map((arg) => arg.trim());
      const paddedString = String.prototype.padStart.call(string, maxLength, fillString);
      expression = expression.replace(match, `'${paddedString}'`);
    });
  }

  expression = expression.replaceAll("'","");	

  matches = expression.match(formatM3MRegex);
  if (matches) {
		matches.forEach((match) => {
			const [, args] = match.split('(');
			const [CCYY_index, classCodeSeq] = args.split(',').map((arg) => arg.trim());
			const formattedM3M = getM3M_sdmx_period(CCYY_index,classCodeSeq);
			expression = expression.replace(match, `'${formattedM3M}'`);
		});
  }
  
  expression = expression.replaceAll("'","");	
  
  matches = expression.match(condifRegex);
  if (matches) {
	   matches.forEach((match) => {
			const [, args] = match.split('(');
			let [condifExpression, truepart,falsepart] = args.split(',').map((arg) => arg.trim());
			falsepart = falsepart.slice(0,-1);
			const condifResult = condif(condifExpression,truepart,falsepart);			
			expression = expression.replace(match, `'${condifResult}'`);
		});	   	
	
  }
    
  matches = expression.match(footNoteRegex);
  if (matches) {
	     matches.forEach((match) => {
			const [, args] = match.split('(');
			let [level, yesno,separator] = args.split(',').map((arg) => arg.trim());
			if (separator)
				separator = separator.slice(0,-1);
			const getFootNoteResult = getFootNote(level,yesno,separator,table_data,cur_sv,cur_sp,cur_cv,cur_cc);
			expression = expression.replace(match, `'${getFootNoteResult}'`);
	
	});
  }
    
  expression = removeHtmlCode(expression);
  expression = expression.replaceAll("'","");	
  expression = expression.trim();
  return expression;
}

function replaceVar(strVar,table_data, cv_lookup_list, cv_cc_lookup_list, sv_lookup, sp_lookup, mdt_record,CCYYObject,timeSeries_Object)  
{
	var strCmd = strVar;
	var strResult;
	
	if (CCYYObject)	
	{
		strCmd = strVar.toUpperCase().replace("{CCYY_RECORD.DEF_CLASS_CODE_DESC}",removeHtmlCode(CCYYObject.def_class_code_desc));
		strCmd = strCmd.toUpperCase().replace("{CCYY_RECORD.DEF_CLASS_CODE_DESC}",removeHtmlCode(CCYYObject.def_class_code_desc));
		strCmd = strCmd.toUpperCase().replace("{CCYY_RECORD.DEF_CLASS_CODE_DESC}",removeHtmlCode(CCYYObject.def_class_code_desc));
	}
	if (timeSeries_Object)
	{
		strCmd = strCmd.toUpperCase().replace("{CCYY_RECORD.DEF_CLASS_CODE_DESC}",removeHtmlCode(timeSeries_Object.ccyy_record.def_class_code_desc));	
		strCmd = strCmd.toUpperCase().replace("{TIME_SERIES_RECORD.DEF_CLASS_CODE_DESC}",removeHtmlCode(timeSeries_Object.time_series_record.def_class_code_desc));
		strCmd = strCmd.toUpperCase().replace("{TIME_SERIES_RECORD.CLASS_CODE}",removeHtmlCode(timeSeries_Object.time_series_record.class_code));		
		strCmd = strCmd.toUpperCase().replace("{TIME_SERIES_RECORD.CLASS_CODE_SEQ}",removeHtmlCode(timeSeries_Object.time_series_record.class_code_seq));

		strCmd = strCmd.toUpperCase().replace("{CCYY_RECORD.DEF_CLASS_CODE_DESC}",removeHtmlCode(timeSeries_Object.ccyy_record.def_class_code_desc));	
		strCmd = strCmd.toUpperCase().replace("{TIME_SERIES_RECORD.DEF_CLASS_CODE_DESC}",removeHtmlCode(timeSeries_Object.time_series_record.def_class_code_desc));
		strCmd = strCmd.toUpperCase().replace("{TIME_SERIES_RECORD.CLASS_CODE}",removeHtmlCode(timeSeries_Object.time_series_record.class_code));		
		strCmd = strCmd.toUpperCase().replace("{TIME_SERIES_RECORD.CLASS_CODE_SEQ}",removeHtmlCode(timeSeries_Object.time_series_record.class_code_seq));		
		
		strCmd = strCmd.toUpperCase().replace("{CCYY_RECORD.DEF_CLASS_CODE_DESC}",removeHtmlCode(timeSeries_Object.ccyy_record.def_class_code_desc));	
		strCmd = strCmd.toUpperCase().replace("{TIME_SERIES_RECORD.DEF_CLASS_CODE_DESC}",removeHtmlCode(timeSeries_Object.time_series_record.def_class_code_desc));
		strCmd = strCmd.toUpperCase().replace("{TIME_SERIES_RECORD.CLASS_CODE}",removeHtmlCode(timeSeries_Object.time_series_record.class_code));		
		strCmd = strCmd.toUpperCase().replace("{TIME_SERIES_RECORD.CLASS_CODE_SEQ}",removeHtmlCode(timeSeries_Object.time_series_record.class_code_seq));
	}	
		
	strResult = parseExpression(strCmd,table_data,sv_lookup,sp_lookup,cv_lookup_list,cv_cc_lookup_list,mdt_record);
	return strResult;
}


function buildSdmxObs(parent_element, xmlDoc, obs_complex_type, table_data, complex_type_map, node_name, sdmx_cv_list, cv_cc_list, stat_var, stat_pres, ccyy_object, time_series, mdt_data, cv_used) {
	var ret = false;
	var attribute_value = '';
	var mdt_result = [];
	var temp_cv_used = cv_used.slice(0);	
	var tv_cv_list  = [];
	
	if (ccyy_object) {
		//attribute_value = ccyy_object.xml_class_code_desc ? ccyy_object.xml_class_code_desc : removeHtmlCode(ccyy_object.def_class_code_desc);
		// get the mdt and sd value
		mdt_result = $.grep(mdt_data, function (obj) { return (obj[CCYY] == ccyy_object.class_var); });
		temp_cv_used.push(CCYY);
		sdmx_cv_list.push(CCYY);
	}	
	if (time_series) {
		
		// get the mdt and sd value
		mdt_result = $.grep(mdt_data, function (obj) { return (obj[CCYY] == time_series.ccyy_index) && (obj[time_series.class_var] == time_series.time_series_index); });		
		temp_cv_used.push(CCYY);
		temp_cv_used.push(time_series.class_var);
		sdmx_cv_list.push(time_series.class_var);
	}	
	var mdt_record = getMdtRecordWithoutExtraCondition(mdt_result, temp_cv_used, null);	
	if (mdt_record) {		
		var sd_value_array = mdt_record.sd_value.split(',');
		sd_value_array = sd_value_array.filter(Boolean);
		var obs_value_suppressed = false;
		var symbol_suppressed = false;
		if (sd_value_array.length > 0) {
			for (var sd_value_index in sd_value_array) {
				var sd_value = sd_value_array[sd_value_index];
				if (all_sd_list[sd_value].obs_value_suppressed == '1') {
					obs_value_suppressed = true;
				}
				if (all_sd_list[sd_value].symbol_suppressed == '1') {
					symbol_suppressed = true;
				}
			}
		}		
		
		var obs_element = xmlDoc.createElement(node_name);		
		parent_element.appendChild(obs_element);		
		var sp_record = table_data.lang_data.sv_list[stat_var].sp_list[stat_pres];		
				
		buildSdmxAttribute(xmlDoc, obs_element, obs_complex_type, table_data, sdmx_cv_list, cv_cc_list, stat_var, stat_pres, mdt_record,ccyy_object,time_series);		
		
		//buildSdmxTVAttribute(xmlDoc, obs_element, obs_complex_type, table_data, tv_cv_list,ccyy_object,time_series );		
		var obs_value = '';
		if (!obs_value_suppressed) {
			obs_value = createObsValueText(mdt_record, sp_record, false);
			obs_value = obs_value.toString();
		}
		setXmlElementAttribute(xmlDoc, obs_element, 'OBS_VALUE', obs_value);
		ret = true;
		
	}
	return ret;

}
function getM3M_sdmx_period(ccyy_index,class_code_seq)
{		
	if (class_code_seq)
	{
		const month = ((parseInt(class_code_seq) + 9) % 12) + 1;
		const paddedMonth = month < 10 ? `0${month}` : month;
		
		if (month==11 || month==12)
			return `${ccyy_index-1}-${paddedMonth}-01/P3M`;
		else 
			return `${ccyy_index}-${paddedMonth}-01/P3M`;
		
	}
	else
		return ccyy_index;

}

function setXmlInnerText(xml_element, text, no_replace) {
	if (!text) {
		text = "";
	}
	try {
		if (no_replace) {
			xml_element.innerHTML = text;
		} else {
			xml_element.innerHTML = htmlEntities(text);
		}
	} catch (ex) {
		xml_element.text = text;
	}
}

function showDownloadXml(table_data) {
	/*if (table_data.xsd_load && table_data.sdmx_load && document.getElementById("download_sdmx")) {
		document.getElementById("download_sdmx").style.display = 'block';
	}*/
	if (checkSdmxExists(table_data)) {
		$("#download_sdmx").show();
	}
}

function generateXml(original_table_id_list) {
	var filename_prefix = "Table";
	var zip = new JSZip();
	if (!original_table_id_list) {
		original_table_id_list = table_id_list;
	}
	original_table_id_list.forEach(function (table_id) {
		var table_data = table_data_list[table_id];
		var theme = table_data.component_data.theme;
		if (!theme) {
			theme = 'THEME';
		}
		var table_prefix = "Table_" + table_id;
		if (window.isWebReport) {
			var seq = $("#table_name_" + table_id).closest(".tab-content").data("seq");
			table_prefix = "Table_" + seq;
		}
		filename_prefix += '_' + table_id;
		var theme_masterdata_style_xsl_filename = table_prefix + "_Masterdata-Style.xsl";
		var theme_masterdata_style_xml_filename = table_prefix + "_Masterdata.xml";
		var theme_metadata_style_xsl_filename = table_prefix + "_Metadata-Style.xsl";
		var theme_metadata_style_xml_filename = table_prefix + "_Metadata.xml";
		var xml_stylesheet_string = "xml-stylesheet";
		var xsl_stylesheet_string = "xsl:stylesheet";
		var master_data_xml_doc = null;
		var master_data_xsl_doc = null;
		var meta_data_xml_doc = null;
		try {
			master_data_xml_doc = document.implementation.createDocument('', theme);
			master_data_xsl_doc = document.implementation.createDocument('', xml_stylesheet_string);
			meta_data_xml_doc = document.implementation.createDocument('', theme);
		} catch (ex) {
			master_data_xml_doc = new ActiveXObject("Microsoft.XMLDOM");
			master_data_xsl_doc = new ActiveXObject("Microsoft.XMLDOM");
			meta_data_xml_doc = new ActiveXObject("Microsoft.XMLDOM");
			
			master_data_xml_doc.async="false";
			master_data_xsl_doc.async="false";
			meta_data_xml_doc.async="false";
			
			//master_data_xsl_doc.loadXML('<?xml version="1.0"?><xsl:stylesheet></xsl:stylesheet>');
			var master_data_xml_doc_element = master_data_xml_doc.createElement(theme);
			var xml_stylesheet_string_element = master_data_xsl_doc.createElement(xml_stylesheet_string);
			var meta_data_xml_doc_element = meta_data_xml_doc.createElement(theme);
			
			master_data_xml_doc.appendChild(master_data_xml_doc_element);
			master_data_xsl_doc.appendChild(xml_stylesheet_string_element);
			meta_data_xml_doc.appendChild(meta_data_xml_doc_element);
		}
		setXmlElementAttribute(master_data_xsl_doc, master_data_xsl_doc.getElementsByTagName(xml_stylesheet_string)[0], "version", '1.0');
		setXmlElementAttribute(master_data_xsl_doc, master_data_xsl_doc.getElementsByTagName(xml_stylesheet_string)[0], "xmlns:xsl", 'http://www.w3.org/1999/XSL/Transform');
		/****************** Master XSL *************************************/
		var template_element = master_data_xsl_doc.createElement('xsl:template');
		setXmlElementAttribute(master_data_xsl_doc, template_element, "match", '/');
		master_data_xsl_doc.getElementsByTagName(xml_stylesheet_string)[0].appendChild(template_element);
		var html_element = master_data_xsl_doc.createElement('html');
		template_element.appendChild(html_element);
		var body_element = master_data_xsl_doc.createElement('body');
		html_element.appendChild(body_element);
		var b_element = master_data_xsl_doc.createElement('b');
		//b_element.innerHTML = 'Master Data';
		setXmlInnerText(b_element, 'Master Data');
		body_element.appendChild(b_element);
		var master_table_element = master_data_xsl_doc.createElement('table');
		setXmlElementAttribute(master_data_xsl_doc, master_table_element, "border", '1');
		body_element.appendChild(master_table_element);
		var master_tr_element = master_data_xsl_doc.createElement('tr');
		setXmlElementAttribute(master_data_xsl_doc, master_tr_element, "bgcolor", '#C0C0C0');
		master_table_element.appendChild(master_tr_element);
		var master_for_each_element = master_data_xsl_doc.createElement('xsl:for-each');
		setXmlElementAttribute(master_data_xsl_doc, master_for_each_element, "select", theme + "/data/table[@name='Master Data']/item");
		master_table_element.appendChild(master_for_each_element);
		var master_for_each_tr_element = master_data_xsl_doc.createElement('tr');
		master_for_each_element.appendChild(master_for_each_tr_element);
		/****************** MASTER XML *************************************/		
		var master_data_element = master_data_xml_doc.createElement('data');
		master_data_xml_doc.getElementsByTagName(theme)[0].appendChild(master_data_element);		
		var table_master_data_element = master_data_xml_doc.createElement('table');
		setXmlElementAttribute(master_data_xml_doc, table_master_data_element, "name", 'Master Data');
		master_data_element.appendChild(table_master_data_element);
		/****************** META XML *************************************/		
		var data_element = meta_data_xml_doc.createElement('data');
		meta_data_xml_doc.getElementsByTagName(theme)[0].appendChild(data_element);		
		var table_entity_element = meta_data_xml_doc.createElement('table');
		setXmlElementAttribute(meta_data_xml_doc, table_entity_element, "name", 'Entity');
		data_element.appendChild(table_entity_element);
		/****************** DATA *************************************/
		var entity_array = [
			{
				"TAB_NAME": "OBS_VALUE",
				"TAB_DESC_EN": "Value of statistics",
				"TAB_DESC_TC": "統計數字的值",
				"TAB_DESC_SC": "统计数字的值"
			},
			{
				"TAB_NAME": "STAT_VAR",
				"TAB_DESC_EN": "Statistical Variable",
				"TAB_DESC_TC": "統計變數",
				"TAB_DESC_SC": "统计变数"
			},
			{
				"TAB_NAME": "STAT_PRES",
				"TAB_DESC_EN": "Statistical Variable Presentation",
				"TAB_DESC_TC": "統計變數展示",
				"TAB_DESC_SC": "统计变数展示"
			},
			{
				"TAB_NAME": "CLASS_VAR",
				"TAB_DESC_EN": "Classification Variable",
				"TAB_DESC_TC": "分類變數",
				"TAB_DESC_SC": "分类变数"
			},
			{
				"TAB_NAME": "CLASS_CODE",
				"TAB_DESC_EN": "Classification Code",
				"TAB_DESC_TC": "分類編碼",
				"TAB_DESC_SC": "分类编码"
			},
			{
				"TAB_NAME": "SD_VALUE",
				"TAB_DESC_EN": "Special Display Value",
				"TAB_DESC_TC": "特殊顯示編碼",
				"TAB_DESC_SC": "特殊显示编码"
			},
			{
				"TAB_NAME": "CLASS_CODE_GROUP",
				"TAB_DESC_EN": "Classification Code Group",
				"TAB_DESC_TC": "分類編碼組別",
				"TAB_DESC_SC": "分类编码组别"
			},
			{
				"TAB_NAME": "PAC",
				"TAB_DESC_EN": "Parent-and-Child Relationship",
				"TAB_DESC_TC": "主次分類編碼關係",
				"TAB_DESC_SC": "主次分类编码关系"
			},
			{
				"TAB_NAME": "Notes of Table",
				"TAB_DESC_EN": "Notes of Table",
				"TAB_DESC_TC": "統計表註釋",
				"TAB_DESC_SC": "统计表注释"
			}
		];		
		var table_title_string = ds_title.table + table_id + ds_title.symbol + table_data.lang_data.tb_title;
		var tab_name = down_text.xml.tab_name;
		var tab_desc = down_text.xml.tab_desc;
		var tab_note = down_text.xml.tab_note;
		var sv_name = down_text.xml.sv_name;
		var sp_name = down_text.xml.sp_name;
		var cv_name = down_text.xml.cv_name;
		var cc_name = down_text.xml.cc_name;
		var ccg_name = down_text.xml.ccg_name;
		var pac_name = down_text.xml.pac_name;
		var sd_name = down_text.xml.sd_name;
		var note_name = down_text.xml.note_name;
		for (var entity_index in entity_array) {
			var entity = entity_array[entity_index];
			var item_element = meta_data_xml_doc.createElement('item');
			table_entity_element.appendChild(item_element);
			var tab_name_element = meta_data_xml_doc.createElement(tab_name);
			setXmlInnerText(tab_name_element, entity.TAB_NAME);
			item_element.appendChild(tab_name_element);	
			var tab_desc_element = meta_data_xml_doc.createElement(tab_desc);
			if (table_data.lang == TC) {
				setXmlInnerText(tab_desc_element, entity.TAB_DESC_TC);
			} else if (table_data.lang == SC) {
				setXmlInnerText(tab_desc_element, entity.TAB_DESC_SC);
			} else {
				setXmlInnerText(tab_desc_element, entity.TAB_DESC_EN);
			}
			item_element.appendChild(tab_desc_element);
		}		
		var schema_array = [
			{
				"TAB_NAME": "Entity",
				"COL_NAME": "TAB_NAME",
				"COL_DESC_EN": "Table name",
				"COL_DESC_TC": "資料表名稱",
				"COL_DESC_SC": "资料表名称",
				"COL_TYPE": "Varchar(30)",
				"PK": "Y"
			},
			{
				"TAB_NAME": "Entity",
				"COL_NAME": "TAB_DESC",
				"COL_DESC_EN": "Table description",
				"COL_DESC_TC": "資料表的描述",
				"COL_DESC_SC": "资料表的描述",
				"COL_TYPE": "NVarchar(250)",
				"PK": "N"
			},
			{
				"TAB_NAME": "Schema",
				"COL_NAME": "TAB_NAME",
				"COL_DESC_EN": "Table name",
				"COL_DESC_TC": "資料表名稱",
				"COL_DESC_SC": "资料表名称",
				"COL_TYPE": "Varchar(30)",
				"PK": "Y"
			},
			{
				"TAB_NAME": "Schema",
				"COL_NAME": "COL_NAME",
				"COL_DESC_EN": "Column name",
				"COL_DESC_TC": "欄位名稱",
				"COL_DESC_SC": "栏位名称",
				"COL_TYPE": "Varchar(30)",
				"PK": "Y"
			},
			{
				"TAB_NAME": "Schema",
				"COL_NAME": "COL_DESC",
				"COL_DESC_EN": "Column description",
				"COL_DESC_TC": "欄位的描述",
				"COL_DESC_SC": "栏位的描述",
				"COL_TYPE": "NVarchar(250)",
				"PK": "N"
			},
			{
				"TAB_NAME": "Schema",
				"COL_NAME": "COL_TYPE",
				"COL_DESC_EN": "Column type",
				"COL_DESC_TC": "欄位類型",
				"COL_DESC_SC": "栏位类型",
				"COL_TYPE": "Varchar(20)",
				"PK": "N"
			},
			{
				"TAB_NAME": "Schema",
				"COL_NAME": "PK",
				"COL_DESC_EN": "Primary key",
				"COL_DESC_TC": "主關鍵碼",
				"COL_DESC_SC": "主关键码",
				"COL_TYPE": "Char(1)",
				"PK": "N"
			},
			{
				"TAB_NAME": "Special Display",
				"COL_NAME": "SD_VALUE",
				"COL_DESC_EN": "Special display code of statistics",
				"COL_DESC_TC": "統計數字的特殊顯示編碼",
				"COL_DESC_SC": "统计数字的特殊显示编码",
				"COL_TYPE": "Char(2)",
				"PK": "Y"
			},
			{
				"TAB_NAME": "Special Display",
				"COL_NAME": "SD_DESC",
				"COL_DESC_EN": "Special display code description",
				"COL_DESC_TC": "特殊顯示編碼的描述",
				"COL_DESC_SC": "特殊显示编码的描述",
				"COL_TYPE": "NVarchar(250)",
				"PK": "N"
			},
			{
				"TAB_NAME": "Statistical Variable Presentation",
				"COL_NAME": "THEME",
				"COL_DESC_EN": "Theme code",
				"COL_DESC_TC": "主題編碼",
				"COL_DESC_SC": "主题编码",
				"COL_TYPE": "Varchar(20)",
				"PK": "Y"
			},
			{
				"TAB_NAME": "Statistical Variable Presentation",
				"COL_NAME": "STAT_VAR",
				"COL_DESC_EN": "Statistical variable",
				"COL_DESC_TC": "統計變數",
				"COL_DESC_SC": "统计变数",
				"COL_TYPE": "Varchar(20)",
				"PK": "Y"
			},
			{
				"TAB_NAME": "Statistical Variable Presentation",
				"COL_NAME": "STAT_PRES",
				"COL_DESC_EN": "Statistical variable presentation code",
				"COL_DESC_TC": "統計變數展示編碼",
				"COL_DESC_SC": "统计变数展示编码",
				"COL_TYPE": "Varchar(20)",
				"PK": "Y"
			},
			{
				"TAB_NAME": "Statistical Variable Presentation",
				"COL_NAME": "STAT_PRES_DESC",
				"COL_DESC_EN": "Statistical variable presentation code description",
				"COL_DESC_TC": "統計變數展示編碼的描述",
				"COL_DESC_SC": "统计变数展示编码的描述",
				"COL_TYPE": "NVarchar(250)",
				"PK": "N"
			},
			{
				"TAB_NAME": "Statistical Variable Presentation",
				"COL_NAME": "STAT_TYPE",
				"COL_DESC_EN": "Statistics type",
				"COL_DESC_TC": "統計數字類型",
				"COL_DESC_SC": "统计数字类型",
				"COL_TYPE": "Varchar(20)",
				"PK": "N"
			},
			{
				"TAB_NAME": "Statistical Variable Presentation",
				"COL_NAME": "STAT_UNIT",
				"COL_DESC_EN": "Unit of measure of statistics",
				"COL_DESC_TC": "統計數字的量度單位",
				"COL_DESC_SC": "统计数字的量度单位",
				"COL_TYPE": "Varchar(20)",
				"PK": "N"
			},
			{
				"TAB_NAME": "Statistical Variable Presentation",
				"COL_NAME": "STAT_UNIT_DESC",
				"COL_DESC_EN": "Unit of measure description",
				"COL_DESC_TC": "量度單位的描述",
				"COL_DESC_SC": "量度单位的描述",
				"COL_TYPE": "NVarchar(250)",
				"PK": "N"
			},
			{
				"TAB_NAME": "Statistical Variable Presentation",
				"COL_NAME": "STAT_MULTIPLIER",
				"COL_DESC_EN": "Multiplier code of statistics",
				"COL_DESC_TC": "統計數字的倍數編碼",
				"COL_DESC_SC": "统计数字的倍数编码",
				"COL_TYPE": "Numeric(2,0)",
				"PK": "N"
			},
			{
				"TAB_NAME": "Statistical Variable Presentation",
				"COL_NAME": "STAT_PRECISION",
				"COL_DESC_EN": "Precision code of statistics",
				"COL_DESC_TC": "統計數字的精確度編碼",
				"COL_DESC_SC": "统计数字的精确度编码",
				"COL_TYPE": "Numeric(2,0)",
				"PK": "N"
			},
			{
				"TAB_NAME": "Classification Variable",
				"COL_NAME": "THEME",
				"COL_DESC_EN": "Theme code",
				"COL_DESC_TC": "主題編碼",
				"COL_DESC_SC": "主题编码",
				"COL_TYPE": "Varchar(20)",
				"PK": "Y"
			},
			{
				"TAB_NAME": "Classification Variable",
				"COL_NAME": "CLASS_VAR",
				"COL_DESC_EN": "Classification variable",
				"COL_DESC_TC": "分類變數",
				"COL_DESC_SC": "分类变数",
				"COL_TYPE": "Varchar(20)",
				"PK": "Y"
			},
			{
				"TAB_NAME": "Classification Variable",
				"COL_NAME": "CLASS_DESC",
				"COL_DESC_EN": "Classification variable description",
				"COL_DESC_TC": "分類變數的描述",
				"COL_DESC_SC": "分类变数的描述",
				"COL_TYPE": "NVarchar(250)",
				"PK": "N"
			},
			{
				"TAB_NAME": "Classification Code",
				"COL_NAME": "THEME",
				"COL_DESC_EN": "Theme code",
				"COL_DESC_TC": "主題編碼",
				"COL_DESC_SC": "主题编码",
				"COL_TYPE": "Varchar(20)",
				"PK": "Y"
			},
			{
				"TAB_NAME": "Classification Code",
				"COL_NAME": "CLASS_VAR",
				"COL_DESC_EN": "Classification variable",
				"COL_DESC_TC": "分類變數",
				"COL_DESC_SC": "分类变数",
				"COL_TYPE": "Varchar(20)",
				"PK": "Y"
			},
			{
				"TAB_NAME": "Classification Code",
				"COL_NAME": "CLASS_CODE",
				"COL_DESC_EN": "Classification code",
				"COL_DESC_TC": "分類編碼",
				"COL_DESC_SC": "分类编码",
				"COL_TYPE": "Varchar(20)",
				"PK": "Y"
			},
			{
				"TAB_NAME": "Classification Code",
				"COL_NAME": "CLASS_CODE_DESC",
				"COL_DESC_EN": "Classification code description",
				"COL_DESC_TC": "分類編碼的描述",
				"COL_DESC_SC": "分类编码的描述",
				"COL_TYPE": "NVarchar(250)",
				"PK": "N"
			},
			{
				"TAB_NAME": "Suggested Classification Group",
				"COL_NAME": "THEME",
				"COL_DESC_EN": "Theme code",
				"COL_DESC_TC": "主題編碼",
				"COL_DESC_SC": "主题编码",
				"COL_TYPE": "Varchar(20)",
				"PK": "Y"
			},
			{
				"TAB_NAME": "Suggested Classification Group",
				"COL_NAME": "CLASS_VAR",
				"COL_DESC_EN": "Classification variable",
				"COL_DESC_TC": "分類變數",
				"COL_DESC_SC": "分类变数",
				"COL_TYPE": "Varchar(20)",
				"PK": "Y"
			},
			{
				"TAB_NAME": "Suggested Classification Group",
				"COL_NAME": "CLASS_TF",
				"COL_DESC_EN": "Suggested classification group number",
				"COL_DESC_TC": "建議分類組別編號",
				"COL_DESC_SC": "建议分类组别编号",
				"COL_TYPE": "Varchar(20)",
				"PK": "Y"
			},
			{
				"TAB_NAME": "Suggested Classification Group",
				"COL_NAME": "CLASS_CODE",
				"COL_DESC_EN": "Classification code",
				"COL_DESC_TC": "分類編碼",
				"COL_DESC_SC": "分类编码",
				"COL_TYPE": "Varchar(20)",
				"PK": "Y"
			},
			{
				"TAB_NAME": "Parent-child Classification Group",
				"COL_NAME": "THEME",
				"COL_DESC_EN": "Theme code",
				"COL_DESC_TC": "主題編碼",
				"COL_DESC_SC": "主题编码",
				"COL_TYPE": "Varchar(20)",
				"PK": "Y"
			},
			{
				"TAB_NAME": "Parent-child Classification Group",
				"COL_NAME": "CLASS_VAR",
				"COL_DESC_EN": "Classification variable",
				"COL_DESC_TC": "分類變數",
				"COL_DESC_SC": "分类变数",
				"COL_TYPE": "Varchar(20)",
				"PK": "Y"
			},
			{
				"TAB_NAME": "Parent-child Classification Group",
				"COL_NAME": "CLASS_CHILD_PAC_CODE",
				"COL_DESC_EN": "Child classification code",
				"COL_DESC_TC": "次分類編碼",
				"COL_DESC_SC": "次分类编码",
				"COL_TYPE": "Varchar(20)",
				"PK": "Y"
			},
			{
				"TAB_NAME": "Parent-child Classification Group",
				"COL_NAME": "CLASS_PARENT_PAC_CODE",
				"COL_DESC_EN": "Parent classification code",
				"COL_DESC_TC": "主分類編碼",
				"COL_DESC_SC": "主分类编码",
				"COL_TYPE": "Varchar(20)",
				"PK": "Y"
			},
			{
				"TAB_NAME": "Notes of Dataset",
				"COL_NAME": "THEME",
				"COL_DESC_EN": "Theme code",
				"COL_DESC_TC": "主題編碼",
				"COL_DESC_SC": "主题编码",
				"COL_TYPE": "Varchar(20)",
				"PK": "N"
			},
			{
				"TAB_NAME": "Notes of Dataset",
				"COL_NAME": "NOTE_DESC",
				"COL_DESC_EN": "Notes",
				"COL_DESC_TC": "注釋",
				"COL_DESC_SC": "注释",
				"COL_TYPE": "NVarchar(1000)",
				"PK": "N"
			},
			{
				"TAB_NAME": "Master Data",
				"COL_NAME": "STAT_VAR",
				"COL_DESC_EN": "Statistical variable",
				"COL_DESC_TC": "統計變數",
				"COL_DESC_SC": "统计变数",
				"COL_TYPE": "Varchar(20)",
				"PK": "N"
			},
			{
				"TAB_NAME": "Master Data",
				"COL_NAME": "STAT_PRES",
				"COL_DESC_EN": "Statistical variable presentation code",
				"COL_DESC_TC": "統計變數展示編碼",
				"COL_DESC_SC": "统计变数展示编码",
				"COL_TYPE": "Varchar(20)",
				"PK": "N"
			},
			{
				"TAB_NAME": "Master Data",
				"COL_NAME": "OBS_VALUE",
				"COL_DESC_EN": "Value of statistics",
				"COL_DESC_TC": "統計數字的值",
				"COL_DESC_SC": "统计数字的值",
				"COL_TYPE": "Numeric(15,5)",
				"PK": "N"
			},
			{
				"TAB_NAME": "Master Data",
				"COL_NAME": "SD_VALUE",
				"COL_DESC_EN": "Special display code of statistics",
				"COL_DESC_TC": "統計數字的特殊顯示編碼",
				"COL_DESC_SC": "统计数字的特殊显示编码",
				"COL_TYPE": "Char(2)",
				"PK": "N"
			},
		];	
		// sort the CV display order
		var cv_order_list = [];
		var table_lang_data = table_data_list[table_id].lang_data_exp;
		for (var cv in table_lang_data.cv_list){
			cv_order_list.push(cv);
		}
		cv_order_list.sort(compareDisplayOrder);
		cv_order_list.forEach(function (v) {
			var cv = table_lang_data.cv_list[v];
			var schema_object = {
				TAB_NAME: "Master Data",
				COL_NAME: v,
				COL_DESC_EN: cv.def_class_desc,
				COL_DESC_TC: cv.def_class_desc,
				COL_DESC_SC: cv.def_class_desc,
				COL_TYPE: "Varchar(20)",
				PK: "N"
			};
			schema_array.splice(schema_array.length - 2, 0, schema_object);
		});
		for (var schema_index in schema_array) {	
			var schema = schema_array[schema_index];
			if (schema.TAB_NAME == "Master Data") {				
				var th_element = master_data_xsl_doc.createElement('th');
				setXmlInnerText(th_element, schema.COL_NAME);
				master_tr_element.appendChild(th_element);				
				var for_each_td_element = master_data_xsl_doc.createElement('td');
				master_for_each_tr_element.appendChild(for_each_td_element);				
				var value_of_element = master_data_xsl_doc.createElement('xsl:value-of');
				setXmlElementAttribute(master_data_xsl_doc, value_of_element, "select", schema.COL_NAME);
				for_each_td_element.appendChild(value_of_element);
			}
		}
		var table_sv_element = meta_data_xml_doc.createElement('table');
		setXmlElementAttribute(meta_data_xml_doc, table_sv_element, "name", sv_name);
		data_element.appendChild(table_sv_element);
		for (var stat_var in table_data.lang_data.sv_list) {
			var sv_record = table_data.lang_data.sv_list[stat_var];
			var item_element = meta_data_xml_doc.createElement('item');
			table_sv_element.appendChild(item_element);			
			var sv_element = meta_data_xml_doc.createElement('STAT_VAR');
			setXmlInnerText(sv_element, stat_var);
			item_element.appendChild(sv_element);			
			var sv_desc_element = meta_data_xml_doc.createElement(tab_desc);
			setXmlInnerText(sv_desc_element, sv_record.def_stat_desc);
			item_element.appendChild(sv_desc_element);			
			for (var note_i = 1; note_i <= 10; note_i++) {
				var note_element = meta_data_xml_doc.createElement(tab_note + '_' + note_i);
				setXmlInnerText(note_element, removeHtmlCode(sv_record['note' + note_i]));
				item_element.appendChild(note_element);
			}
		}
		var table_sp_element = meta_data_xml_doc.createElement('table');
		setXmlElementAttribute(meta_data_xml_doc, table_sp_element, "name", sp_name);
		data_element.appendChild(table_sp_element);		
		for (var stat_var in table_data.lang_data.sv_list) {
			var sv_record = table_data.lang_data.sv_list[stat_var];
			for (var stat_pres in sv_record.sp_list) {
				var sp_record = sv_record.sp_list[stat_pres];
				var item_element = meta_data_xml_doc.createElement('item');
				table_sp_element.appendChild(item_element);				
				var sv_element = meta_data_xml_doc.createElement('STAT_VAR');
				setXmlInnerText(sv_element, stat_var);
				item_element.appendChild(sv_element);				
				var sp_element = meta_data_xml_doc.createElement('STAT_PRES');
				setXmlInnerText(sp_element, stat_pres);
				item_element.appendChild(sp_element);				
				var sp_desc_element = meta_data_xml_doc.createElement(tab_desc);
				setXmlInnerText(sp_desc_element, sp_record.def_stat_pres_desc);
				item_element.appendChild(sp_desc_element);				
				for (var note_i = 1; note_i <= 10; note_i++) {
					var note_element = meta_data_xml_doc.createElement(tab_note + '_' + note_i);
					setXmlInnerText(note_element, removeHtmlCode(sp_record['note' + note_i]));
					item_element.appendChild(note_element);
				}
			}
		}
		var table_cv_element = meta_data_xml_doc.createElement('table');
		setXmlElementAttribute(meta_data_xml_doc, table_cv_element, "name", cv_name);
		data_element.appendChild(table_cv_element);
		var table_cc_element = meta_data_xml_doc.createElement('table');
		setXmlElementAttribute(meta_data_xml_doc, table_cc_element, "name", cc_name);
		data_element.appendChild(table_cc_element);
		var table_sd_element = meta_data_xml_doc.createElement('table');
		setXmlElementAttribute(meta_data_xml_doc, table_sd_element, "name", sd_name);
		data_element.appendChild(table_sd_element);
		var sd_value_list = [];
		for (var sd_index in table_data.sd_used_list) {
			var sd_value = table_data.sd_used_list[sd_index];			
			if (sd_value_list.indexOf(sd_value) >= 0) {
				continue;
			}
			sd_value_list.push(sd_value);
			var sd_record = table_data.sd_list[sd_value];			
			var item_element = meta_data_xml_doc.createElement('item');
			table_sd_element.appendChild(item_element);			
			var sd_value_element = meta_data_xml_doc.createElement('SD_VALUE');
			setXmlInnerText(sd_value_element, sd_value);
			item_element.appendChild(sd_value_element);			
			var sd_desc_element = meta_data_xml_doc.createElement(tab_desc);
			setXmlInnerText(sd_desc_element, sd_record.sd_desc);
			item_element.appendChild(sd_desc_element);
		}		
		var table_ccg_element = meta_data_xml_doc.createElement('table');
		setXmlElementAttribute(meta_data_xml_doc, table_ccg_element, "name", ccg_name);
		data_element.appendChild(table_ccg_element);
		var table_pac_element = meta_data_xml_doc.createElement('table');
		setXmlElementAttribute(meta_data_xml_doc, table_pac_element, "name", pac_name);
		data_element.appendChild(table_pac_element);		
		for (var sort_index in cv_order_list) {
			var cv_comp = cv_order_list[sort_index];
			var cv_record = table_lang_data.cv_list[cv_comp];
			var class_var = cv_comp;
			var cv_item_element = meta_data_xml_doc.createElement('item');
			table_cv_element.appendChild(cv_item_element);			
			var cv_class_var_element = meta_data_xml_doc.createElement('CLASS_VAR');
			setXmlInnerText(cv_class_var_element, class_var);
			cv_item_element.appendChild(cv_class_var_element);			
			var cv_desc_element = meta_data_xml_doc.createElement(tab_desc);
			setXmlInnerText(cv_desc_element, cv_record.def_class_desc);
			cv_item_element.appendChild(cv_desc_element);
			for (var note_i = 1; note_i <= 10; note_i++) {
				var note_element = meta_data_xml_doc.createElement(tab_note + '_' + note_i);
				setXmlInnerText(note_element, removeHtmlCode(cv_record['note' + note_i]));
				cv_item_element.appendChild(note_element);
			}
			var temp_pac_list = cv_record.pac_list;
			for (var pac_index in temp_pac_list) {
				var pac_record = temp_pac_list[pac_index];				
				var pac_item_element = meta_data_xml_doc.createElement('item');
				table_pac_element.appendChild(pac_item_element);
				var pac_class_var_element = meta_data_xml_doc.createElement('CLASS_VAR');
				setXmlInnerText(pac_class_var_element, class_var);
				pac_item_element.appendChild(pac_class_var_element);				
				var pac_parent_element = meta_data_xml_doc.createElement('PARENT_CLASS_CODE_GROUP');
				setXmlInnerText(pac_parent_element, pac_record.parent_class_code_group);
				pac_item_element.appendChild(pac_parent_element);
				var pac_parent_element = meta_data_xml_doc.createElement('PARENT_CLASS_CODE');
				setXmlInnerText(pac_parent_element, pac_record.parent_class_code);
				pac_item_element.appendChild(pac_parent_element);
				var pac_child_element = meta_data_xml_doc.createElement('CHILD_CLASS_CODE_GROUP');
				setXmlInnerText(pac_child_element, pac_record.child_class_code_group);
				pac_item_element.appendChild(pac_child_element);				
				var pac_child_element = meta_data_xml_doc.createElement('CHILD_CLASS_CODE');
				setXmlInnerText(pac_child_element, pac_record.child_class_code);
				pac_item_element.appendChild(pac_child_element);
			}			
			var check_cc_list = [];
			var temp_ccg_list = cv_record.ccg_list;
			for (var ccg_index in temp_ccg_list) {
				var ccg_record = temp_ccg_list[ccg_index];				
				var temp_cc_list = ccg_record.cc_list;				
				for (var class_code in temp_cc_list) {
					var cc_record = temp_cc_list[class_code];					
					// cc
					if (check_cc_list.indexOf(class_code) < 0) {
						check_cc_list.push(class_code);					
						var cc_item_element = meta_data_xml_doc.createElement('item');
						table_cc_element.appendChild(cc_item_element);						
						var cc_class_var_element = meta_data_xml_doc.createElement('CLASS_VAR');
						setXmlInnerText(cc_class_var_element, class_var);
						cc_item_element.appendChild(cc_class_var_element);						
						var cc_class_code_element = meta_data_xml_doc.createElement('CLASS_CODE');
						setXmlInnerText(cc_class_code_element, class_code);
						cc_item_element.appendChild(cc_class_code_element);						
						var cc_desc_element = meta_data_xml_doc.createElement(tab_desc);
						if (cc_record.xml_class_code_desc) {
							setXmlInnerText(cc_desc_element, cc_record.xml_class_code_desc);
						} else {
							setXmlInnerText(cc_desc_element, cc_record.def_class_code_desc);
						}
						cc_item_element.appendChild(cc_desc_element);						
						for (var note_i = 1; note_i <= 10; note_i++) {
							var note_element = meta_data_xml_doc.createElement(tab_note + '_' + note_i);
							setXmlInnerText(note_element, removeHtmlCode(cc_record['note' + note_i]));
							cc_item_element.appendChild(note_element);
						}
					}					
					// ccg
					var ccg_item_element = meta_data_xml_doc.createElement('item');
					table_ccg_element.appendChild(ccg_item_element);					
					var ccg_class_var_element = meta_data_xml_doc.createElement('CLASS_VAR');
					setXmlInnerText(ccg_class_var_element, class_var);
					ccg_item_element.appendChild(ccg_class_var_element);					
					var ccg_class_group_element = meta_data_xml_doc.createElement('CLASS_CODE_GROUP');
					setXmlInnerText(ccg_class_group_element, ccg_index);
					ccg_item_element.appendChild(ccg_class_group_element);						
					var ccg_class_code_element = meta_data_xml_doc.createElement('CLASS_CODE');
					setXmlInnerText(ccg_class_code_element, class_code);
					ccg_item_element.appendChild(ccg_class_code_element);
				}
			}
		}		
		var table_notes_element = meta_data_xml_doc.createElement('table');
		setXmlElementAttribute(meta_data_xml_doc, table_notes_element, "name", note_name);
		data_element.appendChild(table_notes_element);		
		var div = document.createElement("div");
		setXmlInnerText(div, table_data.lang_data.tb_fn, true);
		var tb_fn = div.textContent || div.innerText || "";
		tb_fn = tb_fn.trim();
		if (tb_fn) {
			var note_item_element = meta_data_xml_doc.createElement('item');
			table_notes_element.appendChild(note_item_element);		
			var note_desc_element = meta_data_xml_doc.createElement(tab_desc);
			setXmlInnerText(note_desc_element, tb_fn);
			note_item_element.appendChild(note_desc_element);
		}		
		var notes_th = '';
		var notes_td = '';
		for (var note_i = 1; note_i <= 10; note_i++) {
			notes_th = notes_th + '<th>' + tab_note + '_' + note_i + '</th>';
			notes_td = notes_td + '<td><xsl:value-of select="' + tab_note + '_' + note_i + '"/></td>';
		}
		var metadata_style_xsl = '<?xml version="1.0"?><xsl:stylesheet version="1.0" xmlns:xsl="http://www.w3.org/1999/XSL/Transform"><xsl:template match="/"><html><body><b>' + table_title_string + '</b><table border="1"><tr bgcolor="#C0C0C0"><th>' 
			+ tab_name + '</th><th>' + tab_desc + '</th></tr><xsl:for-each select="THEME_TAG/data/table[@name=\'Entity\']/item"><tr><td><xsl:value-of select="' + tab_name + '"/></td><td><xsl:value-of select="' + tab_desc 
			+ '"/></td></tr></xsl:for-each></table><BR />'
			+ '<b>' + sv_name + '</b><table border="1"><tr bgcolor="#C0C0C0"><th>STAT_VAR</th><th>' + tab_desc + '</th>' + notes_th + '</tr><xsl:for-each select="THEME_TAG/data/table[@name=\'' + sv_name + '\']/item"><tr><td><xsl:value-of select="STAT_VAR"/></td><td><xsl:value-of select="' + tab_desc + '"/></td>' + notes_td + '</tr></xsl:for-each></table><BR />'
			+ '<b>' + sp_name + '</b><table border="1"><tr bgcolor="#C0C0C0"><th>STAT_VAR</th><th>STAT_PRES</th><th>' + tab_desc + '</th>' + notes_th + '</tr><xsl:for-each select="THEME_TAG/data/table[@name=\'' + sp_name + '\']/item"><tr><td><xsl:value-of select="STAT_VAR"/></td><td><xsl:value-of select="STAT_PRES"/></td><td><xsl:value-of select="' + tab_desc + '"/></td>' + notes_td + '</tr></xsl:for-each></table><BR />'
			+ '<b>' + cv_name + '</b><table border="1"><tr bgcolor="#C0C0C0"><th>CLASS_VAR</th><th>' + tab_desc + '</th>' + notes_th + '</tr><xsl:for-each select="THEME_TAG/data/table[@name=\'' + cv_name + '\']/item"><tr><td><xsl:value-of select="CLASS_VAR"/></td><td><xsl:value-of select="' + tab_desc + '"/></td>' + notes_td + '</tr></xsl:for-each></table><BR />'
			+ '<b>' + cc_name + '</b><table border="1"><tr bgcolor="#C0C0C0"><th>CLASS_VAR</th><th>CLASS_CODE</th><th>' + tab_desc + '</th>' + notes_th + '</tr><xsl:for-each select="THEME_TAG/data/table[@name=\'' + cc_name + '\']/item"><tr><td><xsl:value-of select="CLASS_VAR"/></td><td><xsl:value-of select="CLASS_CODE"/></td><td><xsl:value-of select="' + tab_desc + '"/></td>' + notes_td + '</tr></xsl:for-each></table><BR />'
			+ '<b>' + sd_name + '</b><table border="1"><tr bgcolor="#C0C0C0"><th>SD_VALUE</th><th>' + tab_desc + '</th></tr><xsl:for-each select="THEME_TAG/data/table[@name=\'' + sd_name + '\']/item"><tr><td><xsl:value-of select="SD_VALUE"/></td><td><xsl:value-of select="' + tab_desc + '"/></td></tr></xsl:for-each></table><BR />'
			+ '<b>' + ccg_name + '</b><table border="1"><tr bgcolor="#C0C0C0"><th>CLASS_VAR</th><th>CLASS_CODE_GROUP</th><th>CLASS_CODE</th></tr><xsl:for-each select="THEME_TAG/data/table[@name=\'' + ccg_name + '\']/item"><tr><td><xsl:value-of select="CLASS_VAR"/></td><td><xsl:value-of select="CLASS_CODE_GROUP"/></td><td><xsl:value-of select="CLASS_CODE"/></td></tr></xsl:for-each></table><BR />'
			+ '<b>' + pac_name + '</b><table border="1"><tr bgcolor="#C0C0C0"><th>CLASS_VAR</th><th>PARENT_CLASS_CODE_GROUP</th><th>PARENT_CLASS_CODE</th><th>CHILD_CLASS_CODE_GROUP</th><th>CHILD_CLASS_CODE</th></tr><xsl:for-each select="THEME_TAG/data/table[@name=\'' + pac_name + '\']/item"><tr><td><xsl:value-of select="CLASS_VAR"/></td><td><xsl:value-of select="PARENT_CLASS_CODE_GROUP"/></td><td><xsl:value-of select="PARENT_CLASS_CODE"/></td><td><xsl:value-of select="CHILD_CLASS_CODE_GROUP"/></td><td><xsl:value-of select="CHILD_CLASS_CODE"/></td></tr></xsl:for-each></table><BR />'
			+ '<b>' + note_name + '</b><table border="1"><tr bgcolor="#C0C0C0"><th>' + tab_desc + '</th></tr><xsl:for-each select="THEME_TAG/data/table[@name=\'' + note_name + '\']/item"><tr><td><xsl:value-of select="' + tab_desc + '"/></td></tr></xsl:for-each></table><BR /></body></html></xsl:template></xsl:stylesheet>';
		var theme_metadata_style_xsl = metadata_style_xsl.replace(/THEME_TAG/g, theme);		
		var serializer = new XMLSerializer();
		var meta_data_xml_string = '';
		try {
			meta_data_xml_string = serializer.serializeToString(meta_data_xml_doc);
		} catch (ex) {
			meta_data_xml_string = meta_data_xml_doc.xml;
		}
		meta_data_xml_string = '<?xml version="1.0" encoding="UTF-8"?><?xml-stylesheet type="text/xsl" href="' + theme_metadata_style_xsl_filename + '"?>' + meta_data_xml_string;	
		var master_data_xml_string = '';
		var max_mdt_id = mdt_counter[table_id];
		var ori_data_xml = clone(master_data_xml_doc);
		var current_mdt_array = mdt_counter_map[table_id];
		var xml_data_string = "";
		for (var mdt_i = 1; mdt_i <= max_mdt_id; mdt_i++) {
			var mdt_record = current_mdt_array[mdt_i];
			if (!mdt_record) {
				continue;
			}			
			var mdt_item_element = clone(ori_data_xml).createElement('item');//master_data_xml_doc.createElement('item');
			table_master_data_element.appendChild(mdt_item_element);
			var mdt_sv_element = meta_data_xml_doc.createElement('STAT_VAR');
			setXmlInnerText(mdt_sv_element, mdt_record.mdt_sv_index);
			mdt_item_element.appendChild(mdt_sv_element);			
			var mdt_sp_element = meta_data_xml_doc.createElement('STAT_PRES');
			setXmlInnerText(mdt_sp_element, mdt_record.mdt_sp_index);
			mdt_item_element.appendChild(mdt_sp_element);
			cv_order_list.forEach(function (v) {
				var mdt_cv_element = meta_data_xml_doc.createElement(v);
				setXmlInnerText(mdt_cv_element, mdt_record[v]);
				mdt_item_element.appendChild(mdt_cv_element);
			});
			var sd_value_array = mdt_record.sd_value.split(',');
			sd_value_array = sd_value_array.filter(Boolean);
			var obs_value_suppressed = false;
			var symbol_suppressed = false;
			sd_value_array.forEach(function (v) {
				if (all_sd_list[v].obs_value_suppressed == '1') {
					obs_value_suppressed = true;
				}
				if (all_sd_list[v].symbol_suppressed == '1') {
					symbol_suppressed = true;
				}
			});	
			var mdt_obs_element = meta_data_xml_doc.createElement('OBS_VALUE');
			if (obs_value_suppressed) {
				setXmlInnerText(mdt_obs_element, '');
			} else {
				setXmlInnerText(mdt_obs_element, mdt_record.mdt_obs_value_no_sd_text);
			}
			mdt_item_element.appendChild(mdt_obs_element);			
			var mdt_sd_element = meta_data_xml_doc.createElement('SD_VALUE');
			if (symbol_suppressed) {
				setXmlInnerText(mdt_sd_element, '');
			} else {
				setXmlInnerText(mdt_sd_element, mdt_record.sd_value);
			}
			mdt_item_element.appendChild(mdt_sd_element);	
			try {
				xml_data_string += serializer.serializeToString(mdt_item_element);
			} catch (ex) {
				xml_data_string = mdt_item_element.xml;
			}
		}
		try {
			master_data_xml_string = serializer.serializeToString(master_data_xml_doc);
		} catch (ex) {
			master_data_xml_string = master_data_xml_doc.xml;
		}
		master_data_xml_string = master_data_xml_string.replace("/></data>", ">" + xml_data_string + "</table></data>");
		master_data_xml_string = '<?xml version="1.0" encoding="UTF-8"?><?xml-stylesheet type="text/xsl" href="' + theme_masterdata_style_xsl_filename + '"?>' + master_data_xml_string;
		var theme_masterdata_style_xsl = '';
		try {
			theme_masterdata_style_xsl = serializer.serializeToString(master_data_xsl_doc);
		} catch (ex) {
			theme_masterdata_style_xsl = master_data_xsl_doc.xml;
		}
		theme_masterdata_style_xsl = '<?xml version="1.0"?>' + theme_masterdata_style_xsl.replace(xml_stylesheet_string, xsl_stylesheet_string).replace(xml_stylesheet_string, xsl_stylesheet_string);		
		zip.file(theme_masterdata_style_xml_filename, master_data_xml_string);
		zip.file(theme_masterdata_style_xsl_filename, theme_masterdata_style_xsl);
		zip.file(theme_metadata_style_xsl_filename, theme_metadata_style_xsl);
		zip.file(theme_metadata_style_xml_filename, meta_data_xml_string);		
	});
	zip.generateAsync({type:"blob"}).then(function (blob) { // 1) generate the zip file
		if (window.isWebReport && original_table_id_list.length > 1) {
			saveAs(blob, web_element.eCode + "_XML" + "_" + getSiteLang() + ".zip");
		} else {
			saveAs(blob, filename_prefix + "_XML" + "_" + getSiteLang() + ".zip");
		}
		//closeWindowAfterDownload();
    }, function (err) {
        errorLog("XML", "zip file", err);
    });
	if (window.isWebReport) {
		removePageLoading();
	}
}
