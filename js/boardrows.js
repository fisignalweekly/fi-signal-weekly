// Which triggers.json rows appear on the main board. Rows with fi_only: true, and every branch_opening row,
// show only on their institution's /fi/ page (approved Nov 18, 2026). Mirrors is_board_row() in scripts/trigger_types.py.
(function(root){
  var FI_ONLY_TYPES={branch_opening:1};
  function isBoardRow(r){return !!r&&r.fi_only!==true&&!FI_ONLY_TYPES[r.type]}
  function boardRows(rows){return (rows||[]).filter(isBoardRow)}
  var api={isBoardRow:isBoardRow,boardRows:boardRows,FI_ONLY_TYPES:Object.keys(FI_ONLY_TYPES)};
  if(typeof module!=="undefined"&&module.exports)module.exports=api;
  else root.FIBoard=api;
})(typeof globalThis!=="undefined"?globalThis:this);
