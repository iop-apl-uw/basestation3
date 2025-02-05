    function thresh(val, lim1, lim2, good = 'indicatorGreen') {
        if (lim1 < lim2) {
            if (val < lim1)
                return 'indicatorRed';
            else if (val < lim2)
                return 'indicatorYellow';
            else
                return good;
        }
        else {
            if (val > lim1)
                return 'indicatorRed';
            else if (val > lim2)
                return 'indicatorYellow';
            else
                return good;
        }
    }

    function makeAnnunciators(data, maxcount) {
            var indicators = [];

            // annunciators
   //         h = document.createElement('div');
    //        h.classList.add('indicatorBox');
            box = document.createElement('div');
            box.classList.add('indicatorInsideBox');
  //          h.appendChild(box);

            // errors
            if (data.hasOwnProperty('errors') && data.hasOwnProperty('crits')) {
                h = document.createElement('div');
                h.classList.add('indicator');
                h.innerHTML = `errors<br>${data.errors + data.crits}`;
                h.classList.add(thresh(data.errors + data.crits, 0, 0));
                h.name = 'errors';
                indicators.push(h);
            }
            
            // alerts
            if (data.hasOwnProperty('alert')) {
                h = document.createElement('div');
                h.classList.add('indicator');
                h.innerHTML = `alerts<br>${data.alert ? 'yes' : 'none'}`;
                h.classList.add(thresh(data.alert ? 1 : 0, 0, 0));
                h.name = 'alerts';
                indicators.push(h);
            }
 
            // OG efficiency
            if (data.hasOwnProperty('dogEfficiency')) {
                h = document.createElement('div');
                h.title = "over-ground efficiency (flight quality)"
                h.classList.add('indicator');
                h.innerHTML = `OG eff.<br>${(100*data.dogEfficiency).toFixed(0)}%`;
                h.classList.add(thresh(data.dogEfficiency, 0.25, 0.5));
                h.name = 'OGefficiency';
                indicators.push(h);
            }

            // VBD efficiency
            if (data.hasOwnProperty('vbdEfficiency')) {
                h = document.createElement('div');
                h.classList.add('indicator');
                h.innerHTML = `VBD eff.<br>${(100*data.vbdEfficiency).toFixed(0)}%`;
                h.classList.add(thresh(data.vbdEfficiency, 0.25, 0.4));
                h.name = 'VBDefficiency';
                indicators.push(h);
            }

            if (data.hasOwnProperty('volts')) {
                let v = Math.min(...data.volts);
                h = document.createElement('div');
                h.classList.add('indicator');
                h.innerHTML = `voltage<br>${(v).toFixed(2)}V`;
                h.classList.add(thresh(v, 11, 13));
                h.name = 'volts';
                indicators.push(h);
            }

            // mission endurance - planned end date must be defined
            if ('mission' in data && 'planned' in data.mission && data.mission.planned) {
                h = document.createElement('div');
                h.classList.add('indicator');

                planned = new Date(data.mission.planned).getTime() /1000;
                let days = (planned - data.enduranceEndT)/86400;
                if (days < 0)
                    h.title = `mission endurance ${-days.toFixed(0)} days beyond end-date (${data.mission.planned})`;
                else
                    h.title = `mission endurance ${days.toFixed(0)} days short of end-date (${data.mission.planned})`;
                if (days < 0)
                    h.innerHTML = `endur.<br><span>+${-days.toFixed(0)} days</span>`;
                else
                    h.innerHTML = `endur.<br><span>${days.toFixed(0)} days</span>`;
                h.classList.add(thresh(days, 30, 0));
                h.name = 'endurance';
                indicators.push(h);
            }

            // internal pressure
            if (data.hasOwnProperty('internalPressureSlope')) {
                h = document.createElement('div');
                h.classList.add('indicator');
                h.title = `internal pressure slope ${data.internalPressureSlope.toFixed(3)}psi/dv`;
                h.classList.add(thresh(data.internalPressureSlope, 0.01, 0.005));
                h.innerHTML = `intern P<br>${data.internalPressure.toFixed(2)} psi`;
                h.name = 'internalPressere'; 
                indicators.push(h);
            }
            else if (data.hasOwnProperty('internalPressure')) {
                h = document.createElement('div');
                h.classList.add('indicator');
                h.innerHTML = `intern P<br>${data.internalPressure.toFixed(2)} psi`;
                h.classList.add(thresh(data.internalPressure, 12, 10.5));
                h.name = 'internalPressere'; 
                indicators.push(h);
            }


            // humidity
            if (data.hasOwnProperty('humiditySlope')) { 
                h = document.createElement('div');
                h.classList.add('indicator');
                h.title = `humidity slope ${data.humiditySlope.toFixed(2)}/dv`;
                h.classList.add(thresh(data.humiditySlope, 0.2, 0.05));
                h.innerHTML = `humid<br>${data.humidity.toFixed(1)}`;
                h.name = 'humidity';
                indicators.push(h);
            }
            else if (data.hasOwnProperty('humidity')) {
                h = document.createElement('div');
                h.classList.add('indicator');
                h.classList.add(thresh(data.humidity, 60, 55));
                h.innerHTML = `humid<br>${data.humidity.toFixed(1)}`;
                h.name = 'humidity';
                indicators.push(h);
            }

            if (data.hasOwnProperty('sm_pitch')) {
                h = document.createElement('div');
                h.classList.add('indicator');
                h.classList.add(thresh(-data.sm_pitch, 25, 40));
                h.innerHTML = `pitch<br>${data.sm_pitch.toFixed(1)}`;
                h.name = 'pitch';
                indicators.push(h);
            }
           
            if (data.hasOwnProperty('sm_depth')) {
                h = document.createElement('div');
                h.classList.add('indicator');
                h.classList.add(thresh(data.sm_depth, 2.5, 1.5));
                h.innerHTML = `depth<br>${data.sm_depth.toFixed(2)}`;
                h.name = 'depth';
                indicators.push(h);
            }
             

            // volmax
            if (data.hasOwnProperty('impliedVolmaxSlope')) {
                h = document.createElement('div');
                h.classList.add('indicator');
                h.innerHTML = `volmax<br><span>${data.impliedVolmaxSlope.toFixed(1)}cc/dv</span>`;
                h.classList.add(thresh(Math.abs(data.impliedVolmaxSlope), 4, 2));
                h.name = 'volmax';
                indicators.push(h);
            }

            // comms
            if (data.hasOwnProperty('logout') && data.hasOwnProperty('calls')) {
                h = document.createElement('div');
                h.classList.add('indicator');
                let callState = data.logout ? "call finished ok" : "call dropped";
                h.name = 'comms';
                if (data.calls == 1 && data.logout) {
                    h.title = 'calls 1, call finished ok';
                    h.innerHTML = 'comms<br>good';
                    h.classList.add('indicatorGreen');
                }
                else if (data.calls < 3 || data.logout == false) {
                    h.title = `calls ${data.calls}, ${callState}`;
                    h.innerHTML = 'comms<br>fair';
                    h.classList.add('indicatorYellow');
                }
                else {
                    h.title = `calls ${data.calls}, ${callState}`;
                    h.innerHTML = 'comms<br>poor';
                    h.classList.add('indicatorRed');
                }
                indicators.push(h);
            }
            else if (data.hasOwnProperty('calls')) {
                h = document.createElement('div');
                h.classList.add('indicator');
                h.innerHTML = `calls ${data.calls}`;
                h.classList.add(thresh(data.calls, 3, 1));
                h.name = 'comms';
                indicators.push(h);
            }
        
            var reds = [];
            var yellows = []

            for (var i = 0 ; i < indicators.length ; i++) {
                if (indicators[i].classList.contains("indicatorRed")) 
                    reds.push(indicators[i].name);
                else if (indicators[i].classList.contains("indicatorYellow"))
                    yellows.push(indicators[i].name);
            }

            var count = 0;
            var firstExtra = null;
             
            const classes = ["indicatorRed", "indicatorYellow", "indicatorGreen"];
            for (const c of classes) {
                for (var i = 0 ; i < indicators.length ; i++) {
                    if (indicators[i].classList.contains(c)) {
                        box.appendChild(indicators[i]);
                        if (count >= maxcount) {
                            indicators[i].setAttribute('hidden', '');
                            indicators[i].setAttribute('data-extra', '');
                            // console.log('attaching attributes');
                        }
                        if (count == maxcount)
                            firstExtra = indicators[i];

                        count ++;
                    }
                }
            }    

            if (firstExtra) {
                h = document.createElement('span');
                h.classList.add('expander');
                h.innerHTML = '&#9654;'; // tri right, &#9660; is tri down
                h.onclick = function() { 
                    event.stopPropagation();
                    var extra = this.parentElement.querySelectorAll('[data-extra]'); 

                    if (extra[0].hasAttribute('hidden')) {
                        for (e of extra) {
                            e.removeAttribute('hidden');
                        }
                        this.innerHTML = '&#9660;'
                    }
                    else {
                        for (e of extra) {
                            e.setAttribute('hidden', '');
                        }
                        this.innerHTML = '&#9654;'
                    }
                    return true;
                } 
                box.insertBefore(h, firstExtra);
            }

            return { 'element': box, 'reds': reds, 'yellows': yellows };
    }

