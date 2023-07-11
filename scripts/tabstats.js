function getPageEventCoords(evt) {
    var coords = {left:0, top:0};
    if (evt.pageX) {
        coords.left = evt.pageX;
        coords.top = evt.pageY;
    } else if (evt.clientX) {
        coords.left =
            evt.clientX + document.body.scrollLeft - document.body.clientLeft;
        coords.top =
            evt.clientY + document.body.scrollTop - document.body.clientTop;
        // include html element space, if applicable
        if (document.body.parentElement && document.body.parentElement.clientLeft) {
            var bodParent = document.body.parentElement;
            coords.left += bodParent.scrollLeft - bodParent.clientLeft;
            coords.top += bodParent.scrollTop - bodParent.clientTop;
        }
    }
    return coords;
}

var cell1_r;
var cell1_c;
var cell2_r;
var cell2_c;
var num_selected = 0;

function selectCell(cell, evt, tblId) {
      var row, col;
      var table = document.getElementById(tblId);

      var cellR = parseInt(cell.dataset.row) + 1;
      var cellC = parseInt(cell.dataset.col);
      console.log(cellR, cellC, cell.dataset.row, cell.dataset.col);
      if (num_selected == 0) {
         cell1_r = cellR;
         cell1_c = cellC;
         cell.bgColor = 'cyan';
         num_selected ++;
      }
      else if (num_selected == 1) {
         if (cellR != cell1_r && cellC != cell1_c) {
            num_selected = 0;
            table.rows[cell1_r].cells[cell1_c].bgColor = table.rows[cell1_r].bgColor;
            selectCell(cell, evt, tblId);
         }
         else {
            if (cellR < cell1_r) {
               cell2_r = cell1_r;
               cell1_r = cellR;
            }
            else 
               cell2_r = cellR;

            if (cellC < cell1_c) {
               cell2_c = cell1_c;
               cell1_c = cellC;
            }
            else 
               cell2_c = cellC;
            console.log(cell1_r, cell1_c, cell2_r, cell2_c); 
            for (row = cell1_r ; row <= cell2_r ; row++)  {
               for (col = cell1_c; col <= cell2_c ; col++)  {
                  if (table.rows[row].cells[col])
                     table.rows[row].cells[col].bgColor = 'cyan';
               }
            } 
            
            num_selected = 2;
            setTimeout(function() { cellStats(table); }, 10);
            // cellStats(table);
         }
      }
      else if (num_selected == 2) {
         for (row = cell1_r ; row <= cell2_r ; row++)  {
            for (col = cell1_c; col <= cell2_c ; col++)  {
               table.rows[row].cells[col].bgColor = table.rows[row].bgColor;
            }
         } 

         num_selected = 0;
         selectCell(cell, evt, tblId);
      }

      return true;
}

function cellStats(table)
{
   var  row, col;
   var 	sum = 0, mean, stddev;
   var  sum2 = 0;
   var  min, max;
   var	val, n = 0;

   if (num_selected != 2) {
      alert('select a range of table cells first\nby clicking on the end members');
      return false;
   }

   min = max = Number(table.rows[cell1_r].cells[cell1_c].innerHTML);
   for (row = cell1_r ; row <= cell2_r ; row++)  {
      for (col = cell1_c; col <= cell2_c ; col++)  {
         if (table.rows[row].cells[col]) {
            val = Number(table.rows[row].cells[col].innerHTML);
            if (val) {
               if (val > max)
                  max = val;
               else if (val < min)
                  min = val;
         
               sum += val;
               sum2 += val*val; 
               n ++;
            }
         }
      }
   } 
 
   mean = sum / n; 
   stddev = Math.sqrt(sum2/n - mean*mean);
   // alert('Statistics for dives ' + table.rows[cell1_r].cells[0].innerText +
   //      ' to ' + table.rows[cell2_r].cells[0].innerText + '\n' + 
   alert('Statistics over ' + n + ' samples\n' + 
         '_____________________________\n\n' +
         'sum = ' + sum + '\n' + 
         'mean = ' + mean + '\n' +
         'std = ' + stddev + '\n' +
         'min = ' + min + '\n' +
         'max = ' + max + '\n' +
         '_____________________________');

   return false;
}

function strtrim() {
    //Match spaces at beginning and end of text and replace
    //with null strings
    return this.replace(/^\s+/,'').replace(/\s+$/,'');
}

function makeDataTable(id, headers, values)
{
    var tbl = document.createElement('table');
    var thead = document.createElement('thead');
    var tbody = document.createElement('tbody');
    var div = document.createElement('div');
    var tr, tc;
    var i, j;
    const colors = ["#cccccc", "#eeeeee"];


    // div.appendChild(tbl);
    tbl.id = id;
    tbl.classList.add('tabstatsFixedHeader');

    tr = document.createElement('tr');

    for (i = 0 ; i < headers.length ; i++) {
        tc = document.createElement('th');
        tc.appendChild(document.createTextNode(headers[i]));
        tr.appendChild(tc);
    }
    thead.appendChild(tr);
    tbl.appendChild(thead);
    for (i = 0 ; i < values[0].length ; i++) {
        tr = document.createElement('tr');
        tr.style.backgroundColor = colors[i % 2];

        for (j = 0 ; j < values.length ; j++) {
            tc = document.createElement('td');
            tc.dataset.col = j;
            tc.dataset.row = i;
            tc.setAttribute('onclick', 'javascript: selectCell(this, event, "' + id + '");');
            tc.appendChild(document.createTextNode(values[j][i]));
            tr.appendChild(tc);
        }
        tbody.appendChild(tr);
    }
    tbl.appendChild(tbody);

    return tbl; 
}



