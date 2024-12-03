function hookEvent(element, eventName, callback)
{
  if(typeof(element) == "string")
    element = document.getElementById(element);
  if(element == null)
    return;
  if(element.addEventListener)
  {
    element.addEventListener(eventName, callback, false);
  }
  else if(element.attachEvent)
    element.attachEvent("on" + eventName, callback);
}

function unhookEvent(element, eventName, callback)
{
  if(typeof(element) == "string")
    element = document.getElementById(element);
  if(element == null)
    return;
  if(element.removeEventListener)
    element.removeEventListener(eventName, callback, false);
  else if(element.detachEvent)
    element.detachEvent("on" + eventName, callback);
}

function getEventTarget(e)
{
  e = e ? e : window.event;
  return e.target ? e.target : e.srcElement;
}

function cancelEvent(e)
{
  e = e ? e : window.event;
  if(e.stopPropagation)
    e.stopPropagation();
  if(e.preventDefault)
    e.preventDefault();
  e.cancelBubble = true;
  e.cancel = true;
  e.returnValue = false;
  return false;
}

function SpinControlAcceleration(increment, milliseconds)
{
  increment = parseFloat(increment);
  if(isNaN(increment) || increment < 0)
    increment = 0;
  
  milliseconds = parseInt(milliseconds);
  if(isNaN(milliseconds) || milliseconds < 0)
    milliseconds = 0;
    
  this.GetIncrement = function()
  { return increment; }
  
  this.GetMilliseconds = function()
  { return milliseconds; }    
}

function SpinControlAccelerationCollection()
{
  var _array = new Array();
  
  this.GetCount = function()
  { return _array.length; }
  
  this.GetIndex = function(index)
  {
    if(index < 0 || index >= _array.length)
      return null;
    
    return _array[index];
  }
  
  this.RemoveIndex = function(index)
  {
    if(index < 0 || index >= _array.length)
      return;
     
    newArray = new Array(); 
    for(var i=0; i<_array.length; i++)
    {
      if(i == index)
        continue;
      newArray.push(_array[i]);
    }
    _array = newArray;
  }
  
  this.Clear = function()
  {
    _array = new Array();
  }
  
  this.Add = function(spa)
  {
    if(spa.constructor != SpinControlAcceleration)
      return;
      
    if(_array.length == 0)
    {
      _array.push(spa);
      return;
    }
    
    var newSec = spa.GetMilliseconds();
    if(newSec > _array[_array.length-1].GetMilliseconds())
    { 
      _array.push(spa);
      return;
    }
    
    var added = false;
    var newArray = new Array();    
    var indexSec;
    for(var i=0; i<_array.length; i++)
    {
      if(added)
      {
        newArray.push(_array[i]);
      }
      else 
      {
        indexSec = _array[i].GetMilliseconds();
        if(indexSec < newSec)
        {
          newArray.push(_array[i]);        
        }
        else if(indexSec == newSec)
        {
          newArray.push(spa);
          added = true;
        }
        else
        {
          newArray.push(_array[i]);
          newArray.push(spa);
          added = true;
        }
      }
    }
    _array = newArray;
    return;     
  }
}

function SpinControl()
{
  var _this = this;
  
  var _accelerationCollection = new SpinControlAccelerationCollection();
  var _callbackArray = new Array();
  var _currentValue = 1;
  var _maximumVal = 100;
  var _minimumVal = 0;
  var _increment = 1;
  var _width = 35;
  
  var _running = 0;
  var _interval = -1;  
  var _timeStart = 0;
  
  var _bodyEventHooked = false;
  
  var _container = document.createElement("DIV");
  _container.className = 'spinContainer';
  _container.spin = _this;
  
  var _leftEdge = document.createElement("DIV");
  _leftEdge.className = 'spinLeftRightEdge';
  _leftEdge.style.left = '0px';
  
  var _bottomEdge = document.createElement("DIV");
  _bottomEdge.className = 'spinTopBottomEdge';
  _bottomEdge.style.top = '27px';
  
  var _topEdge = document.createElement("DIV");
  _topEdge.className = 'spinTopBottomEdge';
  _topEdge.style.top = '0px';
  
  var _rightEdge = document.createElement("DIV");
  _rightEdge.className = 'spinLeftRightEdge';
  _rightEdge.style.right = '0px';
  
  var _textBox = document.createElement("INPUT");
  _textBox.type = 'text';
  _textBox.className = 'spinInput';
  _textBox.value = _currentValue;
  
  var _upButton = document.createElement("DIV");
  _upButton.className = 'spinUpBtn';
  
  var _downButton = document.createElement("DIV");
  _downButton.className = 'spinDownBtn';
  
  /*
   * Because IE 6 and lower don't support the transparent png background 
   * mask that we use for the buttons.
   * So we use a regular old gif instead.
   * This means that, sadly, the button coloring does not work in IE6 and lower.
   */
  var canChangeBtnColors = true;
  if(document.body.filters)
  {
    var arVersion = navigator.appVersion.split("MSIE");
    var version = parseFloat(arVersion[1]);
    if(version < 7)
    {
      canChangeBtnColors = false;
      _downButton.style.backgroundImage = 'url(icons/spin_control_buttons.gif)';
      _upButton.style.backgroundImage = 'url(icons/spin_control_buttons.gif)';
      _downButton.style.backgroundColor = '#FFFFFF';
      _upButton.style.backgroundColor = '#FFFFFF';
    }
  }
  
  _container.appendChild(_leftEdge);
  _container.appendChild(_bottomEdge);
  _container.appendChild(_topEdge);
  _container.appendChild(_rightEdge);
  _container.appendChild(_textBox);
  _container.appendChild(_upButton);
  _container.appendChild(_downButton);  
  
  function Run()
  {
    if(_running == 0)
      return;
    
    var elapsed = new Date().getTime() - _timeStart;
    var inc = _increment;
    
    if(_accelerationCollection.GetCount() != 0)
    {
      inc = 0;
      for(var i = 0; i<_accelerationCollection.GetCount(); i++)
      {
        if(elapsed < _accelerationCollection.GetIndex(i).GetMilliseconds())
          break;
        
        inc = _accelerationCollection.GetIndex(i).GetIncrement();
      }    
    }
    else if(elapsed < 600)
    {
      return;
    }
    
    DoChange(inc);
  }
  
  function CancelRunning()
  {
    _running = 0;
    if(_interval != -1)
    {
      clearInterval(_interval);
      _interval = -1;
    }
  }
  
  function DoChange(inc)
  {
    var newVal = _currentValue + inc * _running;
    UpdateCurrentValue(newVal);
  }
  
  function StartRunning(newState)
  {
    if(_running != 0)
      CancelRunning();

    _running = newState;
  
    DoChange(_increment);
    
    _timeStart = new Date().getTime();
    _interval = setInterval(Run, 150);
  }
  
  function UpdateCurrentValue(newVal)
  {
    if(newVal <_minimumVal)
      newVal = _minimumVal;
    if(newVal > _maximumVal)
      newVal = _maximumVal;
  
    newVal = Math.round(1000*newVal)/1000;
    
    _textBox.value = newVal;
    if(newVal == _currentValue)
      return;
    
    _currentValue = newVal;
    
    for(var i=0; i<_callbackArray.length; i++)
      _callbackArray[i](_this, _currentValue);
  }
  
  function UpPress(e)
  {
    _upButton.className = 'spinUpBtnPress';
    _downButton.className = 'spinDownBtn';
    StartRunning(1);
    _textBox.focus();
    return cancelEvent(e);
  }
  
  function DownPress(e)
  {
    _upButton.className = 'spinUpBtn';
    _downButton.className = 'spinDownBtnPress';
    StartRunning(-1);
    _textBox.focus();
    return cancelEvent(e);
  }
 
  function UpHover(e)
  {
    if(!_bodyEventHooked)
      hookEvent(document.body, 'mouseover', ClearBtns);
      
    _upButton.className = 'spinUpBtnHover';
    _downButton.className = 'spinDownBtn';
    CancelRunning();
    return cancelEvent(e);
  }
  
  function DownHover(e)
  {
    if(!_bodyEventHooked)
      hookEvent(document.body, 'mouseover', ClearBtns);
      
    _upButton.className = 'spinUpBtn';
    _downButton.className = 'spinDownBtnHover';
    CancelRunning();
    return cancelEvent(e);
  }
  
  function ClearBtns(e)
  {
    var target = getEventTarget(e);
    if(target == _upButton || target == _downButton)
      return;
    _upButton.className = 'spinUpBtn';
    _downButton.className = 'spinDownBtn';
    CancelRunning();
    
    if(_bodyEventHooked)
    {
      unhookEvent(document.body, 'mouseover', ClearBtns);
      _bodyEventHooked = false;
    }
    return cancelEvent(e);
  }
  
  function BoxChange()
  {
    var val = parseFloat(_textBox.value);
    if(isNaN(val))
      val = _currentValue;
    
    UpdateCurrentValue(val);
  }
  
  function MouseWheel(e)
  {
    e = e ? e : window.event;
    var movement = e.detail ? e.detail / -3 : e.wheelDelta/120;
    UpdateCurrentValue(_currentValue + _increment * movement);
    return cancelEvent(e);
  }
  
  function TextFocused(e)
  {
    hookEvent(window, 'DOMMouseScroll', MouseWheel);
    hookEvent(document, 'mousewheel', MouseWheel);
    return cancelEvent(e);
  }
  
  function TextBlur(e)
  {
    unhookEvent(window, 'DOMMouseScroll', MouseWheel);
    unhookEvent(document, 'mousewheel', MouseWheel);
    return cancelEvent(e);
  }
  
  this.StartListening = function()
  {
    hookEvent(_upButton, 'mousedown', UpPress); 
    hookEvent(_upButton, 'mouseup', UpHover);
    hookEvent(_upButton, 'mouseover', UpHover);
    
    hookEvent(_downButton, 'mousedown', DownPress); 
    hookEvent(_downButton, 'mouseup', DownHover);
    hookEvent(_downButton, 'mouseover', DownHover);
    
    hookEvent(_textBox, 'change', BoxChange);
    hookEvent(_textBox, 'focus', TextFocused);
    hookEvent(_textBox, 'blur', TextBlur);
  }
   
  this.StopListening = function()
  {
    unhookEvent(_upButton, 'mousedown', UpPress); 
    unhookEvent(_upButton, 'mouseup', UpHover);
    unhookEvent(_upButton, 'mouseover', UpHover);
    
    unhookEvent(_downButton, 'mousedown', DownPress); 
    unhookEvent(_downButton, 'mouseup', DownHover);
    unhookEvent(_downButton, 'mouseover', DownHover);
    
    unhookEvent(_textBox, 'change', BoxChange);
    unhookEvent(_textBox, 'focus', TextFocused);
    unhookEvent(_textBox, 'blur', TextBlur);
    
    if(_bodyEventHooked)
    {
      unhookEvent(document.body, 'mouseover', ClearBtns);
      _bodyEventHooked = false;
    }
  }
  
  this.SetMaxValue = function(value)
  {
     value = parseFloat(value);
     if(isNaN(value))
       value = 1;
     _maximumVal = value;
       
    UpdateCurrentValue(_currentValue);
  }
   
  this.SetMinValue = function(value)
  {
     value = parseFloat(value);
     if(isNaN(value))
       value = 0;
     _minimumVal = value;
     
    UpdateCurrentValue(_currentValue);
  }
  
  this.SetCurrentValue = function(value)
  {
    value = parseFloat(value);
    if(isNaN(value))
      value = 0;
     
    UpdateCurrentValue(value);
  }
  
  this.SetWidth = function(value)
  {
    value = parseInt(value);
    if(isNaN(value) || value < 25)
      value = 25;
      
    _width = value;
    
    _container.style.width = _width + 'px';
    _bottomEdge.style.width = (_width - 1) + 'px';
    _topEdge.style.width = (_width - 1) + 'px';
    _textBox.style.width = (_width - 5) + 'px';  
  }
  
  this.SetIncrement = function(value)
  {
    value = parseFloat(value);
    if(isNaN(value))
      value = 0;
    if(value < 0)
      value = -value;
    
    _increment = value;
  }
  
  this.SetBackgroundColor = function(color)
  {
    _container.style.backgroundColor = color;
    _textBox.style.backgroundColor = color;
  }
  
  this.SetButtonColor = function(color)
  {
    if(!canChangeBtnColors)
      return;
      
    _upButton.style.backgroundColor = color;
    _downButton.style.backgroundColor = color;
  }
  
  this.SetFontColor = function(color)
  {
    _textBox.style.color = color;
  }
  
  this.SetBorderColor = function(color)
  {
    _topEdge.style.backgroundColor = color;
    _bottomEdge.style.backgroundColor = color;
    _leftEdge.style.backgroundColor = color;
    _rightEdge.style.backgroundColor = color;
  }
  
  this.AttachValueChangedListener = function(listener)
  {
    for(var i=0; i<_callbackArray.length; i++)
      if(_callbackArray[i] == listener)
        return;
        
    _callbackArray.push(listener);  
  }
  
  this.DetachValueChangedListener = function(listener)
  {
    newArray = new Array();
    for(var i=0; i<_callbackArray.length; i++)
      if(_callbackArray[i] != listener)
        newArray.push(_callbackArray[i]);
        
    _callbackArray = newArray;  
  }

  this.GetContainer = function()
  { return _container; }

  this.GetCurrentValue = function()
  { return _currentValue; }

  this.GetMaxValue = function()
  { return _maximumVal; }
   
  this.GetMinValue = function()
  { return _minimumVal; }
   
  this.GetWidth = function()
  { return _width; }
  
  this.GetIncrement = function()
  { return _increment; }
  
  this.GetAccelerationCollection = function()
  { return _accelerationCollection; }
  
  _this.SetWidth(_width);
}
